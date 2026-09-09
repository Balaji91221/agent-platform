"""Redis or Postgres going away must not leak locks or raw 500s."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.main import app
from app.models import Agent, Run
from app.runtime import bus, runs as run_service


async def _agent(session, user):
    a = Agent(user_id=user.id, name="Q", model="claude-sonnet-5", user_prompt="x")
    session.add(a); await session.commit(); await session.refresh(a)
    return a


async def test_a_failed_queue_push_releases_the_agent_and_marks_the_run(session, user, monkeypatch):
    agent = await _agent(session, user)

    async def down(queue, payload):
        raise bus.QueueUnavailable("Redis at redis://x is unreachable")
    monkeypatch.setattr(run_service, "push", down)

    from app.exceptions.errors import UpstreamException
    with pytest.raises(UpstreamException, match="job queue"):
        await run_service.enqueue_run(session, agent, trigger="manual")
    await session.refresh(agent)
    assert agent.is_running is False, "the lock must not leak"
    run = (await session.execute(Run.__table__.select())).fetchone()
    assert run.status == "failed" and "Could not queue" in run.error


async def test_the_api_answers_503_json_when_the_queue_is_down(session, user, monkeypatch):
    agent = await _agent(session, user)

    async def down(queue, payload):
        raise bus.QueueUnavailable("Redis unreachable")
    monkeypatch.setattr(run_service, "push", down)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/agents/{agent.id}/run", headers={"X-User-Id": str(user.id)})
        again = await c.post(f"/agents/{agent.id}/run", headers={"X-User-Id": str(user.id)})
    assert r.status_code >= 500 and r.json()["error"]["code"] and "Redis" in r.text
    assert again.status_code != 409, "the agent must not stay locked after a failed queue push"


async def test_push_refuses_a_local_fallback_unless_enabled(monkeypatch):
    monkeypatch.setattr(settings, "QUEUE_LOCAL_FALLBACK", False)
    monkeypatch.setattr(bus, "_redis", None)
    monkeypatch.setattr(bus, "_redis_checked", True)
    with pytest.raises(bus.QueueUnavailable):
        await bus.push("q", {"x": 1})
    monkeypatch.setattr(settings, "QUEUE_LOCAL_FALLBACK", True)
    await bus.push("q", {"x": 1})
    assert await bus.pop("q", timeout=1) == {"x": 1}


async def test_health_reports_an_unreachable_queue(monkeypatch):
    monkeypatch.setattr(settings, "QUEUE_LOCAL_FALLBACK", False)

    async def dead():
        return False
    monkeypatch.setattr(bus, "redis_alive", dead)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/health")).json()
    assert body["redis"].startswith("unreachable") and body["status"] == "degraded"


async def test_a_database_outage_is_a_clean_503():
    from app.exceptions.handlers import db_unavailable_handler
    from starlette.requests import Request

    scope = {"type": "http", "path": "/agents", "method": "GET", "headers": [], "query_string": b""}
    resp = await db_unavailable_handler(Request(scope), OperationalError("SELECT 1", {}, ConnectionRefusedError()))
    assert resp.status_code == 503 and b"DB_UNAVAILABLE" in resp.body
