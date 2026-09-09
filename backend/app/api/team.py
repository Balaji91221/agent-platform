"""Team, roster, lead, and the thread."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.dependencies.auth import get_current_user
from app.exceptions.errors import ConflictException, NotFoundException, ValidationException
from app.models import Agent, TeamMessage, Teammate, User
from app.schemas.rest import (
    LeadSet,
    TeamMessageIn,
    TeamMessageOut,
    TeamOut,
    TeammateCreate,
    TeammateOut,
    TeammateUpdate,
)
from app.security.ownership import get_or_create_team, get_owned_agent
from app.team.router import post_message, roster

router = APIRouter(prefix="/team", tags=["Team"])


def _shape(mate: Teammate, lead_id: int | None, agent: Agent | None = None) -> TeammateOut:
    return TeammateOut(
        id=mate.id,
        agent_id=mate.agent_id,
        display_name=mate.display_name,
        job_title=mate.job_title,
        description=mate.description,
        colour=mate.colour,
        is_lead=mate.id == lead_id,
        is_running=bool(agent and agent.is_running),
        agent_name=agent.name if agent else "",
    )


async def _shape_all(
    session: AsyncSession, mates: list[Teammate], lead_id: int | None
) -> list[TeammateOut]:
    """One query for every agent, so the roster is not N+1."""
    ids = [m.agent_id for m in mates]
    agents = {}
    if ids:
        rows = (await session.execute(select(Agent).where(Agent.id.in_(ids)))).scalars()
        agents = {a.id: a for a in rows}
    return [_shape(m, lead_id, agents.get(m.agent_id)) for m in mates]


@router.get("", response_model=TeamOut)
async def get_team(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    team = await get_or_create_team(session, user.id)
    mates = await roster(session, team.id)
    return TeamOut(
        id=team.id,
        lead_teammate_id=team.lead_teammate_id,
        teammates=await _shape_all(session, mates, team.lead_teammate_id),
    )


@router.post("/teammates", response_model=TeammateOut, status_code=status.HTTP_201_CREATED)
async def add_teammate(
    payload: TeammateCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    team = await get_or_create_team(session, user.id)
    await get_owned_agent(session, payload.agent_id, user.id)  # ownership check

    # @mentions resolve by name, so two teammates cannot share one.
    taken = await session.execute(
        select(Teammate).where(
            Teammate.team_id == team.id,
            func.lower(Teammate.display_name) == payload.display_name.strip().lower(),
        )
    )
    # A presence check: an existing duplicate pair must not turn this into a 500.
    if taken.scalars().first() is not None:
        raise ConflictException(f"There is already a teammate called {payload.display_name}.")

    mate = Teammate(
        team_id=team.id,
        agent_id=payload.agent_id,
        display_name=payload.display_name,
        job_title=payload.job_title,
        description=payload.description,
        colour=payload.colour,
    )
    session.add(mate)
    await session.commit()
    await session.refresh(mate)

    if payload.make_lead:
        team.lead_teammate_id = mate.id
        await session.commit()

    return _shape(mate, team.lead_teammate_id)


@router.patch("/teammates/{teammate_id}", response_model=TeammateOut)
async def update_teammate(
    teammate_id: int,
    payload: TeammateUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    team = await get_or_create_team(session, user.id)
    mate = await _owned_mate(session, team.id, teammate_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(mate, key, value)
    await session.commit()
    return _shape(mate, team.lead_teammate_id)


@router.delete("/teammates/{teammate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_teammate(
    teammate_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    team = await get_or_create_team(session, user.id)
    mate = await _owned_mate(session, team.id, teammate_id)
    if team.lead_teammate_id == mate.id:
        team.lead_teammate_id = None  # removing the lead leaves the zero-lead state
    await session.delete(mate)
    await session.commit()


@router.put("/lead", response_model=TeamOut)
async def set_lead(
    payload: LeadSet,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Set, change, or clear the lead. `null` is the zero-lead state (FR-13)."""
    team = await get_or_create_team(session, user.id)
    if payload.teammate_id is not None:
        await _owned_mate(session, team.id, payload.teammate_id)
    team.lead_teammate_id = payload.teammate_id
    await session.commit()

    mates = await roster(session, team.id)
    return TeamOut(
        id=team.id,
        lead_teammate_id=team.lead_teammate_id,
        teammates=await _shape_all(session, mates, team.lead_teammate_id),
    )


@router.get("/messages", response_model=list[TeamMessageOut])
async def read_thread(
    limit: int = 100,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """The newest `limit` rows, oldest first — a long thread must still show today."""
    team = await get_or_create_team(session, user.id)
    rows = (
        await session.execute(
            select(TeamMessage)
            .where(TeamMessage.team_id == team.id)
            .order_by(TeamMessage.at.desc(), TeamMessage.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))


@router.delete("/messages", status_code=status.HTTP_204_NO_CONTENT)
async def clear_thread(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Empties the room. The roster and the agents are untouched."""
    from sqlalchemy import delete

    team = await get_or_create_team(session, user.id)
    await session.execute(delete(TeamMessage).where(TeamMessage.team_id == team.id))
    await session.commit()


@router.post("/messages")
async def send_message(
    payload: TeamMessageIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    team = await get_or_create_team(session, user.id)
    if not payload.text.strip():
        raise ValidationException("Message cannot be empty")
    return await post_message(session, team, payload.text.strip())


async def _owned_mate(session: AsyncSession, team_id: int, mate_id: int) -> Teammate:
    result = await session.execute(
        select(Teammate).where(Teammate.id == mate_id, Teammate.team_id == team_id)
    )
    mate = result.scalar_one_or_none()
    if mate is None:
        raise NotFoundException("Teammate", mate_id)
    return mate
