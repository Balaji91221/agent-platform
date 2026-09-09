"""The rules that protect the user: write access, ownership, quiet hours, timeouts."""

import asyncio

import pytest

from app.config import settings
from app.exceptions.errors import NotFoundException
from app.models import Agent, AgentTool, NotificationPref, User
from app.runtime import router
from app.security.crypto import decrypt, encrypt
from app.security.ownership import get_owned_agent


async def _agent(session, user_id: int, tool: str, can_write: bool) -> Agent:
    agent = Agent(user_id=user_id, name="a", model="claude-sonnet-5")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    session.add(AgentTool(agent_id=agent.id, tool_name=tool, can_write=can_write))
    await session.commit()
    return agent


async def test_write_tool_refused_without_can_write(session, user):
    """FR-15 — a send/delete/pay tool is refused unless it was granted."""
    agent = await _agent(session, user.id, "gmail.send", can_write=False)
    _, can_write = await router.build_tool_list(session, agent.id, user.id)

    with pytest.raises(router.ToolDenied):
        await router.call(
            session,
            user_id=user.id,
            tool_name="gmail.send",
            arguments={},
            can_write=can_write,
        )


async def test_write_tool_allowed_when_granted(session, user):
    agent = await _agent(session, user.id, "gmail.send", can_write=True)
    _, can_write = await router.build_tool_list(session, agent.id, user.id)

    result = await router.call(
        session, user_id=user.id, tool_name="gmail.send", arguments={"to": "x@y.z"},
        can_write=can_write,
    )
    assert result["sent"] is True


async def test_read_tool_needs_no_grant(session, user):
    agent = await _agent(session, user.id, "gmail.list_unread", can_write=False)
    _, can_write = await router.build_tool_list(session, agent.id, user.id)
    result = await router.call(
        session, user_id=user.id, tool_name="gmail.list_unread", arguments={},
        can_write=can_write,
    )
    assert result["count"] == 17


async def test_tool_call_is_cancelled_at_the_timeout(session, user, monkeypatch):
    """NFR-8 — a slow tool is cancelled, not waited on."""
    from app.connectors.base import ToolSpec

    async def never_returns(**kwargs):
        await asyncio.sleep(5)

    slow = ToolSpec(
        name="slow.tool", description="", writes=False,
        schema={"type": "object", "properties": {}}, handler=never_returns,
    )
    monkeypatch.setattr(router.registry, "get_tool", lambda name: slow)
    monkeypatch.setattr(router.registry, "provider_for", lambda name: "http")
    monkeypatch.setattr(settings, "TOOL_CALL_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(asyncio.TimeoutError):
        await router.call(
            session, user_id=user.id, tool_name="slow.tool", arguments={}, can_write={}
        )


async def test_ownership_hides_another_users_agent(session, user):
    """NFR-5 — enforced in the query, not the UI. Another user's id is a 404."""
    other = User(email="other@example.com")
    session.add(other)
    await session.commit()
    await session.refresh(other)

    theirs = Agent(user_id=other.id, name="theirs", model="claude-sonnet-5")
    session.add(theirs)
    await session.commit()
    await session.refresh(theirs)

    with pytest.raises(NotFoundException):
        await get_owned_agent(session, theirs.id, user.id)

    assert (await get_owned_agent(session, theirs.id, other.id)).id == theirs.id


def test_credentials_are_never_stored_in_plain_text():
    """NFR-2."""
    secret = "sk-live-do-not-leak"
    blob = encrypt(secret)
    assert secret not in blob
    assert decrypt(blob) == secret


async def test_quiet_hours_hold_success_but_never_failure(session, user):
    """FR-18 — during quiet hours only failures get through."""
    from app.notify.dispatcher import deliver, get_prefs
    from app.models import utcnow

    prefs = await get_prefs(session, user.id)
    now = utcnow().time()
    # A window that certainly contains "now".
    prefs.quiet_from = "00:00"
    prefs.quiet_to = "23:59"
    prefs.notify_on_success = True
    await session.commit()

    held = await deliver(
        session, {"user_id": user.id, "kind": "success", "title": "ran", "body": "", "run_id": None}
    )
    assert held["held"] is True and held["delivered"] == []

    passed = await deliver(
        session, {"user_id": user.id, "kind": "failure", "title": "failed", "body": "", "run_id": None}
    )
    assert passed["held"] is False and "email" in passed["delivered"]
