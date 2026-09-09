"""Prompt variables, the hard run cap, MCP refresh on use, and a real /health."""

import asyncio
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.models import Agent, McpServer, Run, utcnow
from app.runtime import runs as run_service
from app.runtime.executor import prompt_variables, render
from app.runtime.models_api import ModelTurn


async def _agent(session, user, **kw) -> Agent:
    agent = Agent(user_id=user.id, name=kw.get("name", "Digest"), user_prompt=kw.get("user_prompt", "go"),
                  model="claude-sonnet-5")
    session.add(agent); await session.commit(); await session.refresh(agent)
    return agent


def test_render_replaces_known_placeholders_and_keeps_unknown():
    out = render("since {{last_run}} at {{ now }} by {{agent_name}} {{mystery}}",
                 {"last_run": "L", "now": "N", "agent_name": "A"})
    assert out == "since L at N by A {{mystery}}"


async def test_last_run_is_never_then_the_previous_success(session, user):
    agent = await _agent(session, user)
    assert (await prompt_variables(session, agent))["last_run"] == "never"

    ended = utcnow() - timedelta(hours=1)
    session.add(Run(agent_id=agent.id, status="succeeded", ended_at=ended))
    session.add(Run(agent_id=agent.id, status="failed", ended_at=utcnow()))
    await session.commit()

    v = await prompt_variables(session, agent)
    assert v["last_run"].startswith(ended.isoformat(timespec="seconds")[:16])
    assert v["agent_name"] == "Digest" and "T" in v["now"]


async def test_the_model_receives_the_rendered_prompt(session, user, monkeypatch):
    seen = {}

    class Capture:
        async def complete(self, *, system, messages, **kw):
            seen["system"] = system; seen["user"] = messages[0]["content"]
            return ModelTurn(text="ok")

    agent = await _agent(session, user, user_prompt="Mail since {{last_run}} for {{agent_name}}")
    agent.system_prompt = "Today is {{now}}"
    await session.commit()
    monkeypatch.setattr("app.runtime.executor.get_provider", lambda model=None: Capture())

    run = await run_service.enqueue_run(session, agent, trigger="manual")
    await run_service.perform_run(session, run.id)
    assert seen["user"] == "Mail since never for Digest"
    assert "{{" not in seen["system"]


async def test_a_hung_provider_is_cut_off_at_the_cap_and_not_retried(session, user, monkeypatch):
    class Hangs:
        def __init__(self): self.calls = 0
        async def complete(self, **kw):
            self.calls += 1; await asyncio.sleep(5); return ModelTurn(text="late")

    agent = await _agent(session, user); provider = Hangs()
    monkeypatch.setattr("app.runtime.executor.get_provider", lambda model=None: provider)
    monkeypatch.setattr(settings, "RUN_TIMEOUT_SECONDS", 0.2)

    run = await run_service.enqueue_run(session, agent, trigger="manual")
    finished = await run_service.perform_run(session, run.id)
    assert finished.status == "failed" and "exceeded" in (finished.error or "")
    assert provider.calls == 1, "a wall-clock cap is not a transient failure"
    await session.refresh(agent); assert agent.is_running is False


async def test_a_stale_mcp_server_is_refreshed_once_when_its_tool_is_used(session, user, monkeypatch):
    from app.mcp import client as mcp_client
    from app.mcp.client import HandshakeResult
    from app.models import AgentTool
    from app.runtime import router

    server = McpServer(user_id=user.id, url="http://mcp.test/mcp", status="ready",
                       tools_json=[{"name": "search", "description": "old"}],
                       last_handshake_at=utcnow() - timedelta(hours=3))
    session.add(server); await session.commit(); await session.refresh(server)
    agent = await _agent(session, user)
    session.add(AgentTool(agent_id=agent.id, tool_name=f"mcp:{server.id}.search")); await session.commit()

    calls = []
    async def fake_handshake(url, auth_kind="none", credential=None):
        calls.append(url); return HandshakeResult(ok=True, tools=[{"name": "search", "description": "fresh"}])
    monkeypatch.setattr(mcp_client, "handshake", fake_handshake)

    tools, _ = await router.build_tool_list(session, agent.id, user.id)
    assert calls == ["http://mcp.test/mcp"] and tools[0].description == "fresh"
    # Now fresh: a second build does not handshake again.
    await router.build_tool_list(session, agent.id, user.id)
    assert len(calls) == 1


async def test_a_failed_refresh_on_use_drops_the_server_from_the_list_without_raising(session, user, monkeypatch):
    from app.mcp import client as mcp_client
    from app.mcp.client import HandshakeResult
    from app.models import AgentTool
    from app.runtime import router

    server = McpServer(user_id=user.id, url="http://down.test/mcp", status="ready",
                       tools_json=[{"name": "search"}], last_handshake_at=utcnow() - timedelta(hours=3))
    session.add(server); await session.commit(); await session.refresh(server)
    agent = await _agent(session, user)
    session.add(AgentTool(agent_id=agent.id, tool_name=f"mcp:{server.id}.search")); await session.commit()

    async def down(url, auth_kind="none", credential=None):
        return HandshakeResult(ok=False, tools=[], error="connection refused")
    monkeypatch.setattr(mcp_client, "handshake", down)

    tools, _ = await router.build_tool_list(session, agent.id, user.id)
    assert tools == []
    await session.refresh(server)
    assert server.status == "handshake_failed" and "refused" in (server.error or "")


async def test_health_reports_db_and_redis(session):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok" and body["redis"].startswith(("ok", "fallback"))
    assert body["builder_model"] == settings.BUILDER_MODEL
