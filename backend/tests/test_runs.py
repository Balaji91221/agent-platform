"""The run lifecycle: the lock, retries, the caps, and the failure notification."""

import pytest

from app.config import settings
from app.models import Agent, AgentTool, Notification, Run
from app.runtime import runs as run_service
from app.runtime.executor import execute
from app.runtime.logger import RunLogger
from app.runtime.models_api import ModelTurn, ToolCall


class AlwaysFailsProvider:
    """Every model call raises, so the run genuinely fails and retries."""

    def __init__(self):
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        raise RuntimeError("model unreachable")


class LoopsForeverProvider:
    """Always asks for another tool call, so the 20-call budget is what stops it."""

    async def complete(self, **kwargs):
        return ModelTurn(tool_calls=[ToolCall(id="c", name="gmail.list_unread", arguments={})])


async def _agent(session, user, **kw) -> Agent:
    agent = Agent(
        user_id=user.id,
        name=kw.get("name", "Test agent"),
        user_prompt="do the thing",
        model="claude-sonnet-5",
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def test_claim_agent_is_exclusive(session, user):
    """NFR-4 — the second claim on a running agent must fail."""
    agent = await _agent(session, user)
    assert await run_service.claim_agent(session, agent.id) is True
    assert await run_service.claim_agent(session, agent.id) is False

    await run_service.release_agent(session, agent.id)
    assert await run_service.claim_agent(session, agent.id) is True


async def test_enqueue_refuses_a_second_run(session, user):
    from app.exceptions.errors import ConflictException

    agent = await _agent(session, user)
    await run_service.enqueue_run(session, agent, trigger="manual")
    with pytest.raises(ConflictException):
        await run_service.enqueue_run(session, agent, trigger="manual")


async def test_failed_run_retries_three_times_then_notifies(session, user, monkeypatch):
    """FR-7 + FR-17 — 3 attempts, then a failure lands in the feed."""
    agent = await _agent(session, user)
    provider = AlwaysFailsProvider()

    monkeypatch.setattr("app.runtime.executor.get_provider", lambda model=None: provider)
    monkeypatch.setattr(settings, "RETRY_BACKOFF_SECONDS", [0.01, 0.01, 0.01])

    run = await run_service.enqueue_run(session, agent, trigger="manual")
    finished = await run_service.perform_run(session, run.id)

    assert finished.status == "failed"
    assert finished.attempt == settings.MAX_ATTEMPTS == 3
    assert provider.calls == 3, "each attempt must call the model again"

    # The agent lock is released even though the run failed.
    await session.refresh(agent)
    assert agent.is_running is False

    # The notifier's queue got the event; deliver it and check the feed.
    from app.notify.dispatcher import deliver
    from app.runtime.bus import pop

    event = await pop(settings.NOTIFY_QUEUE, timeout=2)
    assert event is not None and event["kind"] == "failure"
    await deliver(session, event)

    rows = (await session.execute(Notification.__table__.select())).fetchall()
    assert len(rows) == 1


async def test_tool_budget_caps_the_run(session, user, monkeypatch):
    """NFR-3 — 20 tool calls and the run is cancelled."""
    agent = await _agent(session, user)
    session.add(AgentTool(agent_id=agent.id, tool_name="gmail.list_unread", can_write=False))
    await session.commit()

    run = Run(agent_id=agent.id, trigger="manual", status="running")
    session.add(run)
    await session.commit()
    await session.refresh(run)

    logger = RunLogger(session, run.id)
    result = await execute(
        session, agent=agent, logger=logger, provider=LoopsForeverProvider()
    )

    assert result.status == "failed"
    assert "tool calls" in (result.error or "")
    assert result.tool_calls == settings.MAX_TOOL_CALLS_PER_RUN + 1


async def test_run_timeout_is_enforced(session, user, monkeypatch):
    """NFR-3 — the wall-clock cap ends the run."""
    agent = await _agent(session, user)
    monkeypatch.setattr(settings, "RUN_TIMEOUT_SECONDS", 0)

    run = Run(agent_id=agent.id, trigger="manual", status="running")
    session.add(run)
    await session.commit()
    await session.refresh(run)

    result = await execute(
        session, agent=agent, logger=RunLogger(session, run.id), provider=LoopsForeverProvider()
    )
    assert result.status == "failed"
    assert "exceeded" in (result.error or "")


async def test_a_rejected_request_is_not_retried(session, user, monkeypatch):
    """A 400 from the provider is deterministic; three attempts would be three failures."""
    from app.exceptions.errors import UpstreamException

    class Rejects:
        def __init__(self): self.calls = 0
        async def complete(self, **kw):
            self.calls += 1
            raise UpstreamException("NVIDIA 400: invalid name", retryable=False)

    agent = await _agent(session, user)
    provider = Rejects()
    monkeypatch.setattr("app.runtime.executor.get_provider", lambda model=None: provider)
    monkeypatch.setattr(settings, "RETRY_BACKOFF_SECONDS", [0.01, 0.01, 0.01])

    run = await run_service.enqueue_run(session, agent, trigger="manual")
    finished = await run_service.perform_run(session, run.id)
    assert finished.status == "failed" and provider.calls == 1


async def test_an_empty_model_answer_is_retried(session, user, monkeypatch):
    """A 200 with nothing in it (overloaded endpoint) must not count as success."""
    class FlakyThenFine:
        def __init__(self): self.calls = 0
        async def complete(self, **kw):
            self.calls += 1
            return ModelTurn() if self.calls == 1 else ModelTurn(text="Done properly.")

    agent = await _agent(session, user)
    provider = FlakyThenFine()
    monkeypatch.setattr("app.runtime.executor.get_provider", lambda model=None: provider)
    monkeypatch.setattr(settings, "RETRY_BACKOFF_SECONDS", [0.01, 0.01, 0.01])

    run = await run_service.enqueue_run(session, agent, trigger="manual")
    finished = await run_service.perform_run(session, run.id)
    assert finished.status == "succeeded" and finished.attempt == 2
    assert finished.output == "Done properly."
