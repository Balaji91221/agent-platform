"""Plan NFR-5 — every read of a user-owned row goes through here.

Ownership is a WHERE clause, never a UI concern. Anything that forgets to call
`owned()` will return another user's rows, so the API layer never builds a bare
select() against these tables.
"""

from typing import TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.errors import NotFoundException
from app.models import Agent, Connection, McpServer, Run, Team

T = TypeVar("T")


def owned(model: type[T], user_id: int) -> Select:
    """A select() already narrowed to one user's rows."""
    return select(model).where(model.user_id == user_id)  # type: ignore[attr-defined]


async def get_owned(session: AsyncSession, model: type[T], obj_id: int, user_id: int) -> T:
    """Fetch one row or raise 404 — never 403, so ids cannot be probed."""
    result = await session.execute(
        owned(model, user_id).where(model.id == obj_id)  # type: ignore[attr-defined]
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFoundException(model.__name__, obj_id)
    return row


async def get_owned_agent(session: AsyncSession, agent_id: int, user_id: int) -> Agent:
    return await get_owned(session, Agent, agent_id, user_id)


async def get_owned_run(session: AsyncSession, run_id: int, user_id: int) -> Run:
    """Runs carry no user_id, so ownership is proved through the parent agent."""
    result = await session.execute(
        select(Run).join(Agent, Run.agent_id == Agent.id).where(
            Run.id == run_id, Agent.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFoundException("Run", run_id)
    return row


async def get_owned_connection(session: AsyncSession, cid: int, user_id: int) -> Connection:
    return await get_owned(session, Connection, cid, user_id)


async def get_owned_mcp_server(session: AsyncSession, sid: int, user_id: int) -> McpServer:
    return await get_owned(session, McpServer, sid, user_id)


async def get_or_create_team(session: AsyncSession, user_id: int) -> Team:
    """Plan §2: one team per user, created on first read."""
    result = await session.execute(owned(Team, user_id))
    team = result.scalars().first()
    if team is None:
        team = Team(user_id=user_id, lead_teammate_id=None)
        session.add(team)
        await session.commit()
        await session.refresh(team)
    return team
