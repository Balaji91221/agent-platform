"""A notification points at the run's agent, can be read one at a time, and the
prefs say where email actually goes."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.models import Agent, Notification, Run


@pytest.fixture
async def client(session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _failed_run(session, user) -> tuple[Agent, Run]:
    agent = Agent(user_id=user.id, name="Digest", model="claude-sonnet-5")
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    run = Run(agent_id=agent.id, trigger="manual", status="failed", error="boom")
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return agent, run


async def test_feed_rows_carry_the_agent_behind_the_run(client, session, user):
    agent, run = await _failed_run(session, user)
    session.add(Notification(user_id=user.id, kind="failure", title="Digest failed", run_id=run.id))
    session.add(Notification(user_id=user.id, kind="expiry", title="gmail expired", run_id=None))
    await session.commit()

    r = await client.get("/notifications", headers={"X-User-Id": str(user.id)})
    assert r.status_code == 200
    by_title = {n["title"]: n for n in r.json()}
    assert by_title["Digest failed"]["agent_id"] == agent.id
    assert by_title["Digest failed"]["agent_name"] == "Digest"
    assert by_title["gmail expired"]["agent_id"] is None
    assert by_title["gmail expired"]["agent_name"] == ""


async def test_one_notification_can_be_marked_read_alone(client, session, user):
    a = Notification(user_id=user.id, kind="failure", title="one")
    b = Notification(user_id=user.id, kind="failure", title="two")
    session.add_all([a, b])
    await session.commit()

    h = {"X-User-Id": str(user.id)}
    r = await client.post(f"/notifications/{a.id}/read", headers=h)
    assert r.status_code == 200 and r.json() == {"marked": 1}
    rows = {n["title"]: n["is_read"] for n in (await client.get("/notifications", headers=h)).json()}
    assert rows == {"one": True, "two": False}


async def test_marking_someone_elses_notification_is_a_404(client, session, user):
    from app.models import User

    other = User(email="other@example.com")
    session.add(other)
    await session.commit()
    await session.refresh(other)
    theirs = Notification(user_id=other.id, kind="failure", title="private")
    session.add(theirs)
    await session.commit()

    r = await client.post(f"/notifications/{theirs.id}/read", headers={"X-User-Id": str(user.id)})
    assert r.status_code == 404


async def test_prefs_say_where_email_goes(client, session, user, monkeypatch):
    h = {"X-User-Id": str(user.id)}
    monkeypatch.setattr(settings, "NOTIFY_EMAIL", "")
    assert (await client.get("/notifications/prefs", headers=h)).json()["email_to"] == user.email

    monkeypatch.setattr(settings, "NOTIFY_EMAIL", "ops@example.com")
    assert (await client.get("/notifications/prefs", headers=h)).json()["email_to"] == "ops@example.com"
    # The read-only field is ignored on write rather than rejected.
    r = await client.put("/notifications/prefs", json={"email_on": False, "email_to": "x@y.z"}, headers=h)
    assert r.status_code == 200 and r.json()["email_to"] == "ops@example.com"
    assert r.json()["email_on"] is False
