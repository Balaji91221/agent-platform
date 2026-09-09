"""Release locks a dead process left behind.

`enqueue_run` marks an agent running *before* it queues the job — that is what
stops two ticks queueing the same agent. The cost is that a process killed
between the claim and the finish leaves the flag set, and that agent can never
run again. This sweep is the other half of that trade.

Two shapes of wreckage:
  1. An agent flagged running with no queued or running run — an orphaned claim.
  2. A run still `running` long past the wall-clock cap — its worker is gone.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Agent, Run, as_utc, utcnow

logger = logging.getLogger("recovery")

# Past this, a run that is still going has no worker behind it.
def _abandoned_after() -> timedelta:
    return timedelta(seconds=settings.RUN_TIMEOUT_SECONDS * 2)


async def sweep(session: AsyncSession) -> dict[str, int]:
    """Return the counts, so a caller can log what it cleaned up."""
    now = utcnow()
    cutoff = now - _abandoned_after()

    # 1. Runs whose worker died mid-flight.
    stale_runs = (
        await session.execute(
            select(Run).where(Run.status.in_(["queued", "running"]))
        )
    ).scalars().all()

    failed = 0
    for run in stale_runs:
        started = as_utc(run.started_at) or as_utc(run.created_at)
        if started is None or started > cutoff:
            continue
        run.status = "failed"
        run.error = "Abandoned: no worker finished this run."
        run.ended_at = now
        failed += 1
    if failed:
        await session.commit()

    # 2. Agents still flagged running with nothing actually in flight.
    busy_agents = (
        await session.execute(select(Agent).where(Agent.is_running.is_(True)))
    ).scalars().all()

    released = 0
    for agent in busy_agents:
        active = (
            await session.execute(
                select(Run).where(
                    Run.agent_id == agent.id, Run.status.in_(["queued", "running"])
                )
            )
        ).scalars().first()
        if active is not None:
            continue
        await session.execute(
            update(Agent).where(Agent.id == agent.id).values(is_running=False)
        )
        released += 1
    if released:
        await session.commit()

    if failed or released:
        logger.warning(
            "recovered %s abandoned run(s) and released %s stuck agent lock(s)",
            failed,
            released,
        )
    return {"runs_failed": failed, "locks_released": released}
