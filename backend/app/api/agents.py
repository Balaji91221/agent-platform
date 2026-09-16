"""Agent CRUD, run-now, pause/resume."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.dependencies.auth import get_current_user
from app.exceptions.errors import ConflictException, LimitReachedException, ValidationException
from app.a2a import card as a2a_card
from app.a2a import tokens as a2a_tokens
from app.cicd import jenkins
from app.connectors import registry
from app.mcp.cache import qualified_names
from app.models import Agent, AgentTool, McpServer, Run, RunLog, Schedule, Team, Teammate, User
from app.runtime.runs import enqueue_run
from app.scheduler.cron import describe, next_due, preview, validate_cron, zone
from app.schemas.agent import (
    A2AOut,
    AgentCreate,
    AgentOut,
    AgentUpdate,
    DeploymentOut,
    JobRunOut,
    RunOut,
    ScheduleOut,
    ToolGrant,
)
from app.security.ownership import get_owned_agent, owned

router = APIRouter(prefix="/agents", tags=["Agents"])


async def _shape(session: AsyncSession, agent: Agent) -> AgentOut:
    tools = (
        await session.execute(select(AgentTool).where(AgentTool.agent_id == agent.id))
    ).scalars().all()
    sched = (
        await session.execute(select(Schedule).where(Schedule.agent_id == agent.id))
    ).scalar_one_or_none()

    schedule_out = None
    if sched is not None:
        schedule_out = ScheduleOut(
            cron=sched.cron,
            timezone=sched.timezone,
            is_paused=sched.is_paused,
            next_due_at=sched.next_due_at,
            words=describe(sched.cron),
            next_runs=preview(sched.cron, sched.timezone),
        )

    return AgentOut(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        system_prompt=agent.system_prompt,
        user_prompt=agent.user_prompt,
        model=agent.model,
        is_running=agent.is_running,
        created_at=agent.created_at,
        tools=[ToolGrant(tool_name=t.tool_name, can_write=t.can_write) for t in tools],
        schedule=schedule_out,
    )


def _deployment(agent: Agent, runs: list[jenkins.JobRun]) -> DeploymentOut:
    slug = jenkins.agent_slug(agent.id, agent.name)
    return DeploymentOut(
        agent_id=agent.id,
        slug=slug,
        host_entry=jenkins.host_entry(slug),
        hosts_file=settings.AGENT_HOSTS_FILE,
        enabled=settings.JENKINS_ENABLED,
        jobs=[JobRunOut(**vars(r)) for r in runs],
        a2a=A2AOut(
            enabled=settings.A2A_ENABLED,
            card_url=a2a_card.card_url(agent.id),
            endpoint_url=a2a_card.endpoint_url(agent.id),
            token=a2a_tokens.issue(agent.id),
        ),
    )


async def _allowed_tool_names(session: AsyncSession, user_id: int) -> set[str]:
    """Built-in tools plus every tool on this user's ready MCP servers."""
    names = set(registry.builtin_tools())
    servers = (
        await session.execute(
            select(McpServer).where(McpServer.user_id == user_id, McpServer.status == "ready")
        )
    ).scalars().all()
    for server in servers:
        names.update(qualified_names(server))
    return names


async def _check_tools(session: AsyncSession, user_id: int, grants: list[ToolGrant]) -> None:
    """Reject unknown names *before* any row is written, so a 422 leaves nothing behind."""
    allowed = await _allowed_tool_names(session, user_id)
    unknown = sorted({g.tool_name for g in grants} - allowed)
    if unknown:
        raise ValidationException(f"Unknown tool(s): {', '.join(unknown)}")


async def _apply_tools(
    session: AsyncSession, agent_id: int, user_id: int, grants: list[ToolGrant]
) -> None:
    await _check_tools(session, user_id, grants)
    seen: set[str] = set()
    await session.execute(delete(AgentTool).where(AgentTool.agent_id == agent_id))
    for grant in grants:
        if grant.tool_name in seen:
            continue
        seen.add(grant.tool_name)
        session.add(
            AgentTool(agent_id=agent_id, tool_name=grant.tool_name, can_write=grant.can_write)
        )
    await session.commit()


async def _apply_schedule(session: AsyncSession, agent_id: int, spec) -> None:
    validate_cron(spec.cron)
    existing = (
        await session.execute(select(Schedule).where(Schedule.agent_id == agent_id))
    ).scalar_one_or_none()
    due = next_due(spec.cron, spec.timezone)
    if existing is None:
        session.add(
            Schedule(
                agent_id=agent_id,
                cron=spec.cron,
                timezone=spec.timezone,
                is_paused=spec.is_paused,
                next_due_at=due,
            )
        )
    else:
        existing.cron = spec.cron
        existing.timezone = spec.timezone
        existing.is_paused = spec.is_paused
        existing.next_due_at = due
    await session.commit()


@router.get("", response_model=list[AgentOut])
async def list_agents(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    rows = (await session.execute(owned(Agent, user.id))).scalars().all()
    return [await _shape(session, a) for a in rows]


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    count = (
        await session.execute(
            select(func.count()).select_from(Agent).where(Agent.user_id == user.id)
        )
    ).scalar() or 0
    if count >= settings.MAX_AGENTS_PER_USER:
        raise LimitReachedException(
            f"Your plan allows {settings.MAX_AGENTS_PER_USER} agents. Upgrade for more."
        )
    if payload.model not in settings.MODEL_IDS:
        raise ValidationException(f"Unknown model '{payload.model}'")
    await _check_tools(session, user.id, payload.tools)

    agent = Agent(
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
        user_prompt=payload.user_prompt,
        model=payload.model,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    if payload.tools:
        await _apply_tools(session, agent.id, user.id, payload.tools)
    if payload.schedule:
        await _apply_schedule(session, agent.id, payload.schedule)

    # Provision CI and the host entry. A Jenkins outage must not undo an agent
    # the user has already been told about, so the result is logged, not raised.
    await jenkins.trigger(settings.JENKINS_CREATE_JOB, agent.id, agent.name)

    return await _shape(session, agent)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _shape(session, await get_owned_agent(session, agent_id, user.id))


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: int,
    payload: AgentUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    agent = await get_owned_agent(session, agent_id, user.id)
    data = payload.model_dump(exclude_unset=True, exclude={"tools", "schedule"})
    if "model" in data and data["model"] not in settings.MODEL_IDS:
        raise ValidationException(f"Unknown model '{data['model']}'")
    if payload.tools is not None:
        await _check_tools(session, user.id, payload.tools)
    if payload.schedule is not None:
        validate_cron(payload.schedule.cron)
        zone(payload.schedule.timezone)
    for key, value in data.items():
        setattr(agent, key, value)
    await session.commit()

    if payload.tools is not None:
        await _apply_tools(session, agent.id, user.id, payload.tools)
    if "schedule" in payload.model_fields_set:
        if payload.schedule is None:
            # An explicit null means "run only by hand from now on".
            await session.execute(delete(Schedule).where(Schedule.agent_id == agent.id))
            await session.commit()
        else:
            await _apply_schedule(session, agent.id, payload.schedule)

    await session.refresh(agent)
    return await _shape(session, agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    agent = await get_owned_agent(session, agent_id, user.id)
    if agent.is_running:
        raise ConflictException("This agent is running. Wait for it to finish, then delete it.")

    # Tear the host entry down while the agent still exists — the job needs its
    # name to build the slug.
    await jenkins.trigger(settings.JENKINS_DELETE_JOB, agent.id, agent.name)

    # Everything that references the agent goes first, or Postgres refuses.
    run_ids = select(Run.id).where(Run.agent_id == agent.id)
    await session.execute(delete(RunLog).where(RunLog.run_id.in_(run_ids)))
    await session.execute(delete(Run).where(Run.agent_id == agent.id))
    await session.execute(delete(AgentTool).where(AgentTool.agent_id == agent.id))
    await session.execute(delete(Schedule).where(Schedule.agent_id == agent.id))

    # If it sat on the team, take it off — and clear the lead if that was it.
    # Explicit statements, executed now: with no ORM relationships declared the
    # unit of work would otherwise delete the agent before its teammate row.
    mates = (
        await session.execute(select(Teammate).where(Teammate.agent_id == agent.id))
    ).scalars().all()
    for mate in mates:
        team = await session.get(Team, mate.team_id)
        if team is not None and team.lead_teammate_id == mate.id:
            team.lead_teammate_id = None
    await session.execute(delete(Teammate).where(Teammate.agent_id == agent.id))
    await session.flush()

    await session.delete(agent)
    await session.commit()


@router.post("/{agent_id}/run", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def run_now(
    agent_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """409 when a run is already in progress — never stack (plan NFR-4)."""
    agent = await get_owned_agent(session, agent_id, user.id)
    return await enqueue_run(session, agent, trigger="manual")


@router.post("/{agent_id}/pause", response_model=AgentOut)
async def pause(
    agent_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _set_paused(session, agent_id, user.id, True)


@router.post("/{agent_id}/resume", response_model=AgentOut)
async def resume(
    agent_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _set_paused(session, agent_id, user.id, False)


async def _set_paused(
    session: AsyncSession, agent_id: int, user_id: int, paused: bool
) -> AgentOut:
    agent = await get_owned_agent(session, agent_id, user_id)
    sched = (
        await session.execute(select(Schedule).where(Schedule.agent_id == agent.id))
    ).scalar_one_or_none()
    if sched is None:
        raise ValidationException("This agent has no schedule")
    sched.is_paused = paused
    if not paused:
        sched.next_due_at = next_due(sched.cron, sched.timezone)
    await session.commit()
    return await _shape(session, agent)


@router.get("/{agent_id}/runs", response_model=list[RunOut])
async def agent_runs(
    agent_id: int,
    limit: int = 20,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    agent = await get_owned_agent(session, agent_id, user.id)
    rows = (
        await session.execute(
            select(Run)
            .where(Run.agent_id == agent.id)
            .order_by(Run.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


@router.post("/{agent_id}/deploy", response_model=DeploymentOut)
async def deploy_agent(
    agent_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Run the deploy job. Returns as soon as the build has a number."""
    agent = await get_owned_agent(session, agent_id, user.id)
    run = await jenkins.trigger(settings.JENKINS_DEPLOY_JOB, agent.id, agent.name, wait=True)
    return _deployment(agent, [run])


@router.get("/{agent_id}/deployment", response_model=DeploymentOut)
async def agent_deployment(
    agent_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """The host entry plus the latest build of each of the three jobs."""
    agent = await get_owned_agent(session, agent_id, user.id)
    return _deployment(agent, await jenkins.jobs_for_agent(agent.id))
