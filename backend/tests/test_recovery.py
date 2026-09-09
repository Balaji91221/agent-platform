"""Locks must not survive the process that took them."""

from datetime import timedelta

from app.config import settings
from app.models import Agent, Run, utcnow
from app.runtime.recovery import sweep


async def _agent(session, user, running: bool) -> Agent:
    agent = Agent(user_id=user.id, name="a", model="claude-sonnet-5", is_running=running)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_an_orphaned_claim_is_released(session, user):
    """Claimed, then the process died before the run row could be queued."""
    agent = await _agent(session, user, running=True)

    result = await sweep(session)

    await session.refresh(agent)
    assert agent.is_running is False
    assert result["locks_released"] == 1


async def test_a_live_run_keeps_its_lock(session, user):
    """A genuinely running agent must not be disturbed."""
    agent = await _agent(session, user, running=True)
    session.add(Run(agent_id=agent.id, trigger="manual", status="running", started_at=utcnow()))
    await session.commit()

    result = await sweep(session)

    await session.refresh(agent)
    assert agent.is_running is True
    assert result["locks_released"] == 0
    assert result["runs_failed"] == 0


async def test_a_run_abandoned_past_the_cap_is_failed_and_released(session, user):
    agent = await _agent(session, user, running=True)
    long_ago = utcnow() - timedelta(seconds=settings.RUN_TIMEOUT_SECONDS * 3)
    run = Run(agent_id=agent.id, trigger="manual", status="running", started_at=long_ago)
    session.add(run)
    await session.commit()
    await session.refresh(run)

    result = await sweep(session)

    await session.refresh(run)
    await session.refresh(agent)
    assert run.status == "failed"
    assert "Abandoned" in (run.error or "")
    assert agent.is_running is False
    assert result == {"runs_failed": 1, "locks_released": 1}


async def test_sweeping_a_clean_database_changes_nothing(session, user):
    await _agent(session, user, running=False)
    assert await sweep(session) == {"runs_failed": 0, "locks_released": 0}
