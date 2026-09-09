"""Everything that happens around a run: the lock, retries, and the outcome.

All three trigger paths (schedule, manual, team) end here, so the running-flag
rule and the retry policy live in exactly one place.
"""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions.errors import UpstreamException, ConflictException
from app.models import Agent, Run, utcnow
from app.runtime import executor
from app.runtime.bus import QueueUnavailable, push, run_channel, publish
from app.runtime.logger import RunLogger


async def claim_agent(session: AsyncSession, agent_id: int) -> bool:
    """Plan NFR-4 — flip is_running False→True atomically. False means busy."""
    result = await session.execute(
        update(Agent)
        .where(Agent.id == agent_id, Agent.is_running.is_(False))
        .values(is_running=True)
    )
    await session.commit()
    return result.rowcount == 1


async def release_agent(session: AsyncSession, agent_id: int) -> None:
    await session.execute(
        update(Agent).where(Agent.id == agent_id).values(is_running=False)
    )
    await session.commit()


async def enqueue_run(
    session: AsyncSession, agent: Agent, trigger: str, prompt_override: str | None = None
) -> Run:
    """Claim the agent, create the run row, then put the job on the queue.

    Claiming first is what stops the next scheduler tick queueing the same agent
    a second time.
    """
    if not await claim_agent(session, agent.id):
        raise ConflictException(f"Agent {agent.id} is already running")

    run = Run(agent_id=agent.id, trigger=trigger, status="queued", attempt=0)
    session.add(run)
    await session.commit()
    await session.refresh(run)

    try:
        await push(
            settings.JOB_QUEUE,
            {"run_id": run.id, "agent_id": agent.id, "prompt_override": prompt_override},
        )
    except QueueUnavailable as exc:
        # Nothing will ever pick this run up: say so on the row and give the
        # agent back, or it stays locked until the sweep declares it abandoned.
        run.status = "failed"
        run.error = f"Could not queue the run: {exc}"
        run.ended_at = utcnow()
        await release_agent(session, agent.id)
        await session.commit()
        raise UpstreamException(
            "The job queue (Redis) is unreachable, so the run was not started.", retryable=False
        ) from exc
    return run


async def perform_run(
    session: AsyncSession, run_id: int, prompt_override: str | None = None
) -> Run:
    """Execute a queued run, retrying on failure with 1s/2s/4s backoff (FR-7)."""
    run = await session.get(Run, run_id)
    if run is None:
        raise ValueError(f"Run {run_id} not found")
    agent = await session.get(Agent, run.agent_id)
    if agent is None:
        raise ValueError(f"Agent {run.agent_id} not found")

    logger = RunLogger(session, run.id)
    await logger.load_seq()

    run.status = "running"
    run.started_at = utcnow()
    await session.commit()

    started = time.monotonic()
    result = None

    try:
        for attempt in range(1, settings.MAX_ATTEMPTS + 1):
            run.attempt = attempt
            await session.commit()

            await logger.info(
                f"run r_{run.id} started · trigger={run.trigger} · attempt {attempt}"
            )
            try:
                # The executor checks the clock between steps; this is the hard
                # stop for a provider call that never returns.
                result = await asyncio.wait_for(
                    executor.execute(
                        session, agent=agent, logger=logger, prompt_override=prompt_override
                    ),
                    timeout=settings.RUN_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                # The cancel may have landed mid-statement; a rollback makes the
                # session usable again for the status write below.
                await session.rollback()
                await session.refresh(run)
                await session.refresh(agent)
                await logger.error(f"run cancelled · exceeded {settings.RUN_TIMEOUT_SECONDS}s")
                result = executor.ExecutionResult(
                    "failed", "", f"exceeded {settings.RUN_TIMEOUT_SECONDS}s", retryable=False
                )
            if result.status == "succeeded":
                break
            if not result.retryable:
                await logger.error("not retrying · the request was rejected, not dropped")
                break

            if attempt < settings.MAX_ATTEMPTS:
                wait = settings.RETRY_BACKOFF_SECONDS[
                    min(attempt - 1, len(settings.RETRY_BACKOFF_SECONDS) - 1)
                ]
                await logger.warn(
                    f"attempt {attempt}/{settings.MAX_ATTEMPTS} failed · retrying in {wait}s"
                )
                await asyncio.sleep(wait)

        assert result is not None
        run.status = result.status
        run.output = result.output
        run.error = result.error
    finally:
        run.ended_at = utcnow()
        run.duration_seconds = round(time.monotonic() - started, 3)
        await session.commit()
        # The thread reply lands *before* the lock is released: the Team page
        # stops polling the moment it sees the agent idle, so a reply written
        # after that point would not show until a refresh.
        await _post_team_reply(session, agent, run)
        await release_agent(session, agent.id)
        await publish(run_channel(run.id), {"event": "done", "status": run.status})

    await _schedule_next(session, agent.id)
    await _drain_team_queue(session, agent)
    await _notify(session, agent, run)
    await session.refresh(run)
    return run


async def _schedule_next(session: AsyncSession, agent_id: int) -> None:
    from app.scheduler.cron import advance_schedule

    await advance_schedule(session, agent_id)


async def _teammate_for(session: AsyncSession, agent: Agent):
    from sqlalchemy import select

    from app.models import Teammate

    return (
        await session.execute(select(Teammate).where(Teammate.agent_id == agent.id))
    ).scalars().first()


async def _post_team_reply(session: AsyncSession, agent: Agent, run: Run) -> None:
    """A run started from the team thread answers back into that thread.

    Without this the thread only ever shows "Picked it up." — the teammate's
    actual output would live on the run and never reach the room. Runs inside
    perform_run's ``finally``, so it must never raise past itself.
    """
    if run.trigger != "team":
        return

    from app.models import TeamMessage

    try:
        mate = await _teammate_for(session, agent)
        if mate is None:
            return

        if run.status == "succeeded":
            text = (run.output or "").strip() or "Finished, with nothing to report."
            kind = "agent"
        else:
            why = (run.error or "the run failed").rstrip(".")
            text = f"could not finish this one: {why}."
            kind = "blocked"

        session.add(
            TeamMessage(
                team_id=mate.team_id,
                kind=kind,
                from_teammate_id=mate.id,
                text=text,
                run_id=run.id,
            )
        )
        await session.commit()
    except Exception:  # noqa: BLE001 - the run's own outcome must still be recorded
        await session.rollback()
        logging.getLogger("runs").exception("team reply for run %s not written", run.id)


async def _drain_team_queue(session: AsyncSession, agent: Agent) -> None:
    """Start the next message waiting for this teammate, now the agent is free."""
    from app.team.router import drain_queue

    mate = await _teammate_for(session, agent)
    if mate is None:
        return
    try:
        await drain_queue(session, mate)
    except Exception:  # noqa: BLE001 - a stuck queue must not fail the finished run
        await session.rollback()
        logging.getLogger("runs").exception("queued team message for agent %s not started", agent.id)


async def _notify(session: AsyncSession, agent: Agent, run: Run) -> None:
    """Hand the outcome to the notifier's own queue (NFR-11) — never send inline."""
    from app.notify.dispatcher import queue_run_outcome

    await queue_run_outcome(session, agent, run)
