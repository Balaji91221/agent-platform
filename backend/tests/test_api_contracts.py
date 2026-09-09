"""HTTP-level contracts the UI depends on, run through the real app."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

J = {"Content-Type": "application/json"}


@pytest.fixture
async def client(session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _agent(client, name="A", **extra) -> dict:
    r = await client.post("/agents", json={"name": name, "model": "claude-sonnet-5", **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def test_delete_agent_with_runs_and_teammate_succeeds(client):
    """Was a 500 on Postgres: runs and teammates still pointed at the agent."""
    a = await _agent(client, tools=[{"tool_name": "gmail.list_unread", "can_write": False}])
    assert (await client.post(f"/agents/{a['id']}/run")).status_code == 202

    # Finish the run in-process so the agent is idle and has run rows.
    from app.db import async_session_factory
    from app.runtime.runs import perform_run

    async with async_session_factory() as s:
        run_id = (await client.get(f"/agents/{a['id']}/runs")).json()[0]["id"]
        await perform_run(s, run_id)

    r = await client.post(
        "/team/teammates",
        json={"agent_id": a["id"], "display_name": "Zed", "job_title": "t", "make_lead": True},
    )
    assert r.status_code == 201

    assert (await client.delete(f"/agents/{a['id']}")).status_code == 204
    assert (await client.get(f"/agents/{a['id']}")).status_code == 404
    team = (await client.get("/team")).json()
    assert team["lead_teammate_id"] is None and team["teammates"] == []


async def test_delete_running_agent_is_refused(client):
    a = await _agent(client)
    assert (await client.post(f"/agents/{a['id']}/run")).status_code == 202
    r = await client.delete(f"/agents/{a['id']}")
    assert r.status_code == 409


async def test_patch_schedule_null_removes_it(client):
    a = await _agent(client, schedule={"cron": "0 9 * * *", "timezone": "UTC"})
    assert a["schedule"] is not None
    r = await client.patch(f"/agents/{a['id']}", json={"schedule": None})
    assert r.status_code == 200 and r.json()["schedule"] is None


async def test_patch_without_schedule_key_leaves_it_alone(client):
    a = await _agent(client, schedule={"cron": "0 9 * * *", "timezone": "UTC"})
    r = await client.patch(f"/agents/{a['id']}", json={"name": "B"})
    assert r.json()["schedule"]["cron"] == "0 9 * * *"


async def test_unknown_tool_name_is_rejected(client):
    r = await client.post(
        "/agents",
        json={"name": "A", "model": "claude-sonnet-5",
              "tools": [{"tool_name": "nope.tool", "can_write": False}]},
    )
    assert r.status_code == 422
    assert "nope.tool" in r.json()["error"]["message"]


async def test_duplicate_teammate_name_is_refused(client):
    a = await _agent(client, "A")
    b = await _agent(client, "B")
    ok = await client.post("/team/teammates", json={"agent_id": a["id"], "display_name": "Ravi", "job_title": "x"})
    assert ok.status_code == 201
    dup = await client.post("/team/teammates", json={"agent_id": b["id"], "display_name": "ravi", "job_title": "y"})
    assert dup.status_code == 409


@pytest.mark.parametrize("bad", ["not a url", "ftp://x", ""])
async def test_mcp_server_needs_an_http_url(client, bad):
    r = await client.post("/mcp-servers", json={"url": bad})
    assert r.status_code == 422


@pytest.mark.parametrize("bad", ["25:99", "9:00", "abc"])
async def test_quiet_hours_must_be_hh_mm(client, bad):
    body = {"email_on": True, "slack_dm_on": False, "webhook_on": False,
            "webhook_url": None, "quiet_from": bad, "quiet_to": None, "notify_on_success": False}
    assert (await client.put("/notifications/prefs", json=body)).status_code == 422


async def test_builder_draft_guesses_tools_from_the_words(client):
    r = await client.post("/builder/draft", json={"text": "summarise my inbox and post it to slack"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "draft"
    assert set(body["draft"]["tools"]) >= {"gmail.list_unread", "slack.post_message"}


async def test_prefs_read_survives_a_bad_value_already_stored(client, session, user):
    """Rows written before the HH:MM validator existed must still be readable."""
    from sqlalchemy import update
    from app.models import NotificationPref

    await session.execute(
        update(NotificationPref).where(NotificationPref.user_id == user.id).values(quiet_from="25:99")
    )
    await session.commit()

    r = await client.get("/notifications/prefs", headers={"X-User-Id": str(user.id)})
    assert r.status_code == 200
    assert r.json()["quiet_from"] is None, "the bad value is read as unset, not as a 500"


async def test_a_rejected_create_leaves_no_agent_behind(client, user):
    """Sweep found agent 'Bad tool' persisted after its POST returned 422."""
    r = await client.post("/agents", json={"name": "Bad tool", "user_prompt": "x",
                                           "tools": [{"tool_name": "nope.tool"}]})
    assert r.status_code == 422
    listing = await client.get("/agents")
    assert [a["name"] for a in listing.json()] == []


async def test_a_rejected_patch_changes_nothing(client, user):
    made = (await client.post("/agents", json={"name": "Keep", "user_prompt": "x"})).json()
    r = await client.patch(f"/agents/{made['id']}", json={"name": "Changed",
                                                          "tools": [{"tool_name": "nope.tool"}]})
    assert r.status_code == 422
    after = (await client.get(f"/agents/{made['id']}")).json()
    assert after["name"] == "Keep" and after["tools"] == []
    bad_cron = await client.patch(f"/agents/{made['id']}", json={"name": "Changed2",
                                                                 "schedule": {"cron": "nope", "timezone": "UTC"}})
    assert bad_cron.status_code == 422
    assert (await client.get(f"/agents/{made['id']}")).json()["name"] == "Keep"


async def test_a_partial_prefs_update_leaves_the_other_toggles_alone(client, user):
    first = await client.put("/notifications/prefs", json={"slack_dm_on": True, "email_on": True})
    assert first.status_code == 200 and first.json()["slack_dm_on"] is True
    second = await client.put("/notifications/prefs", json={"webhook_on": True, "webhook_url": "https://x.test/h"})
    body = second.json()
    assert body["slack_dm_on"] is True and body["email_on"] is True and body["webhook_on"] is True
