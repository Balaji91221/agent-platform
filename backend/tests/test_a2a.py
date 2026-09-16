"""A2A v1.0: the card, the token gate, and one synchronous SendMessage.

`A2A_ENABLED` is off in the shared test environment, so each test that needs the
surface turns it on and puts it back — that also proves the flag really gates.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.a2a import tokens
from app.config import settings
from app.main import app


@pytest.fixture
async def client(session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture
def a2a_on():
    settings.A2A_ENABLED = True
    yield
    settings.A2A_ENABLED = False


async def _agent(client, **extra) -> dict:
    body = {"name": "Daily Digest", "model": "claude-sonnet-5", **extra}
    r = await client.post("/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _send(text: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "role": "ROLE_USER",
                "messageId": "m-1",
                "parts": [{"text": text}],
            }
        },
    }


def _auth(agent_id: int) -> dict:
    return {"Authorization": f"Bearer {tokens.issue(agent_id)}"}


async def test_card_is_hidden_until_a2a_is_enabled(client):
    agent = await _agent(client)
    assert settings.A2A_ENABLED is False
    r = await client.get(f"/a2a/agents/{agent['id']}/.well-known/agent-card.json")
    assert r.status_code == 404


async def test_card_has_the_shape_the_spec_requires(client, a2a_on):
    agent = await _agent(client, description="Reads overnight mail.")
    card = (await client.get(f"/a2a/agents/{agent['id']}/.well-known/agent-card.json")).json()

    assert card["name"] == "Daily Digest"
    assert card["defaultInputModes"] == ["text/plain"]
    # v1.0 replaced the single `url` with a list of protocol bindings.
    interface = card["supportedInterfaces"][0]
    assert interface["protocolBinding"] == "JSONRPC"
    assert interface["url"].endswith(f"/a2a/agents/{agent['id']}")
    # Nothing beyond card + synchronous send is built, so nothing else is claimed.
    assert card["capabilities"] == {
        "streaming": False,
        "pushNotifications": False,
        "extendedAgentCard": False,
    }
    assert "agentToken" in card["securitySchemes"]


async def test_tools_become_skills_a_caller_can_choose_on(client, a2a_on):
    agent = await _agent(client, tools=[{"tool_name": "gmail.list_unread", "can_write": False}])
    card = (await client.get(f"/a2a/agents/{agent['id']}/.well-known/agent-card.json")).json()

    ids = [s["id"] for s in card["skills"]]
    assert ids == ["run", "tool:gmail.list_unread"]
    assert "read only" in card["skills"][1]["description"]


async def test_send_without_a_token_is_refused(client, a2a_on):
    """401 on the wire, and an error in the envelope, so either client sees it.

    Not -32600: the spec defines that as a malformed Request object, which a
    correctly-shaped call with no credential is not.
    """
    agent = await _agent(client)
    r = await client.post(f"/a2a/agents/{agent['id']}", json=_send("hello"))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == -32000


async def test_send_with_another_agents_token_is_refused(client, a2a_on):
    mine = await _agent(client)
    theirs = await _agent(client, name="Other")
    r = await client.post(
        f"/a2a/agents/{mine['id']}", json=_send("hello"), headers=_auth(theirs["id"])
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == -32000


async def test_send_message_runs_the_agent_and_returns_a_terminal_task(client, a2a_on):
    agent = await _agent(client)
    r = await client.post(
        f"/a2a/agents/{agent['id']}", json=_send("Summarise today"), headers=_auth(agent["id"])
    )

    task = r.json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    # The task id names the run it created, so a caller can find it in history.
    runs = (await client.get(f"/agents/{agent['id']}/runs")).json()
    assert task["id"] == f"run-{runs[0]['id']}"
    # The answer rides in an artifact, not in the status message.
    assert task["artifacts"][0]["parts"][0]["text"]
    assert task["history"][0]["role"] == "ROLE_USER"


async def test_the_run_is_recorded_like_any_other(client, a2a_on):
    """An A2A call is a first-class run: it shows in history with its own trigger."""
    agent = await _agent(client)
    await client.post(
        f"/a2a/agents/{agent['id']}", json=_send("Summarise today"), headers=_auth(agent["id"])
    )

    runs = (await client.get(f"/agents/{agent['id']}/runs")).json()
    assert len(runs) == 1
    assert runs[0]["trigger"] == "a2a"
    assert runs[0]["status"] == "succeeded"


async def test_a_message_with_no_text_is_invalid_params(client, a2a_on):
    agent = await _agent(client)
    body = _send("x")
    body["params"]["message"]["parts"] = [{"file": {"uri": "http://x/y.png"}}]
    r = await client.post(f"/a2a/agents/{agent['id']}", json=body, headers=_auth(agent["id"]))
    assert r.json()["error"]["code"] == -32602


async def test_a_method_the_card_does_not_claim_is_not_found(client, a2a_on):
    agent = await _agent(client)
    body = _send("hello")
    body["method"] = "SendStreamingMessage"
    r = await client.post(f"/a2a/agents/{agent['id']}", json=body, headers=_auth(agent["id"]))
    assert r.json()["error"]["code"] == -32601


async def test_deployment_exposes_the_card_url_and_token(client):
    agent = await _agent(client)
    a2a = (await client.get(f"/agents/{agent['id']}/deployment")).json()["a2a"]

    assert a2a["enabled"] is False
    assert a2a["card_url"].endswith("/.well-known/agent-card.json")
    assert a2a["token"] == tokens.issue(agent["id"])


async def test_task_timestamp_is_rfc3339_utc(client, a2a_on):
    """Regression: a naive `.isoformat()` is rejected by conformant clients.

    The official a2a-sdk parses `status.timestamp` as a protobuf Timestamp and
    refuses a string with no zone — which is what SQLite's naive datetime gives.
    """
    from datetime import datetime

    agent = await _agent(client)
    r = await client.post(
        f"/a2a/agents/{agent['id']}", json=_send("hi"), headers=_auth(agent["id"])
    )

    stamp = r.json()["result"]["task"]["status"]["timestamp"]
    assert stamp.endswith("Z"), stamp
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
