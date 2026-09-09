"""Wakes every 30 seconds, finds what is due, queues it. Nothing else.

Deliberately tiny (plan §8): it must never block behind slow work, or one stuck
agent would delay every other agent's 9am run.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session_factory
from app.exceptions.errors import ConflictException
from app.models import Agent, Schedule, utcnow
from app.runtime.recovery import sweep
from app.runtime.runs import enqueue_run

logger = logging.getLogger("scheduler")


async def due_agents(session: AsyncSession) -> list[tuple[Agent, Schedule]]:
    """Agents whose next_due_at has passed and that are not already running."""
    now = utcnow()
    result = await session.execute(
        select(Agent, Schedule)
        .join(Schedule, Schedule.agent_id == Agent.id)
        .where(
            Schedule.is_paused.is_(False),
            Schedule.next_due_at.is_not(None),
            Schedule.next_due_at <= now,
            Agent.is_running.is_(False),
        )
    )
    return list(result.all())


async def tick() -> int:
    """One pass. Returns how many runs were queued."""
    queued = 0
    async with async_session_factory() as session:
        # Clear anything a dead process left locked before looking for work.
        await sweep(session)

        for agent, schedule in await due_agents(session):
            try:
                await enqueue_run(session, agent, trigger="schedule")
            except ConflictException:
                # Another tick or a manual run claimed it first — correct, skip.
                continue
            # Move the schedule forward immediately so this tick cannot re-queue it.
            from app.scheduler.cron import next_due

            schedule.next_due_at = next_due(schedule.cron, schedule.timezone)
            await session.commit()
            queued += 1
            logger.info("queued agent %s (%s)", agent.id, agent.name)
    return queued


async def run_forever() -> None:
    logger.info("scheduler up · tick every %ss", settings.SCHEDULER_TICK_SECONDS)
    while True:
        try:
            await tick()
        except Exception:  # noqa: BLE001 - the ticker must survive a bad row
            logger.exception("tick failed")
        await asyncio.sleep(settings.SCHEDULER_TICK_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(name)s: %(message)s")
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
