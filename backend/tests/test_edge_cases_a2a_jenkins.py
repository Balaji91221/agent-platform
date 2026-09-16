"""Edge cases for the A2A surface and the Jenkins wiring, end to end through the app.

A2A: every malformed envelope, every auth shape, a failing run, a busy agent, two
callers at once, and the card tracking the agent row.

Jenkins: a fake Jenkins behind `httpx.MockTransport` so each failure shape the
real one can produce is exercised — down, crumb refused, job missing, 500,
queue item cancelled, queue item never scheduled, non-JSON bodies.
"""

import asyncio
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient, MockTransport

from app.a2a import tokens
from app.cicd import jenkins
from app.config import settings
from app.main import app
from app.runtime import executor as executor_module
from app.runtime.models_api import ModelProvider


@pytest.fixture
async def client(session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture
def a2a_on():
    settings.A2A_ENABLED = True
    yield
    settings.A2A_ENABLED = False


@pytest.fixture
def one_attempt():
    """A failing run retries 1s/2s/4s; the failure tests do not need to wait for that."""
    before = settings.MAX_ATTEMPTS
    settings.MAX_ATTEMPTS = 1
    yield
    settings.MAX_ATTEMPTS = before


async def _agent(client, **extra) -> dict:
    body = {"name": "Daily Digest", "model": "claude-sonnet-5", "a2a_enabled": True, **extra}
    r = await client.post("/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _send(text: str, **message_extra) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "role": "ROLE_USER",
                "messageId": "m-1",
                "parts": [{"text": text}],
                **message_extra,
            }
        },
    }


def _auth(agent_id: int) -> dict:
    return {"Authorization": f"Bearer {tokens.issue(agent_id)}"}


async def _rpc(client, agent_id: int, body: Any, headers: dict | None = None):
    return await client.post(
        f"/a2a/agents/{agent_id}", json=body, headers=headers or _auth(agent_id)
    )


# --------------------------------------------------------------------------- A2A envelope


async def test_a_json_array_body_is_invalid_request(client, a2a_on):
    """JSON-RPC batch calls are not supported; an array is not a Request object."""
    agent = await _agent(client)
    r = await _rpc(client, agent["id"], [_send("hi")])
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32600
    assert r.json()["id"] is None


async def test_a_body_that_is_not_json_is_parse_error(client, a2a_on):
    agent = await _agent(client)
    r = await client.post(
        f"/a2a/agents/{agent['id']}",
        content=b"{not json",
        headers={**_auth(agent["id"]), "content-type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32700


async def test_an_empty_body_is_parse_error(client, a2a_on):
    agent = await _agent(client)
    r = await client.post(f"/a2a/agents/{agent['id']}", content=b"", headers=_auth(agent["id"]))
    assert r.json()["error"]["code"] == -32700


async def test_wrong_jsonrpc_version_is_invalid_request_and_echoes_id(client, a2a_on):
    agent = await _agent(client)
    body = _send("hi")
    body["jsonrpc"] = "1.0"
    body["id"] = "req-9"
    r = await _rpc(client, agent["id"], body)
    assert r.json()["error"]["code"] == -32600
    assert r.json()["id"] == "req-9"


async def test_missing_method_is_method_not_found(client, a2a_on):
    agent = await _agent(client)
    body = _send("hi")
    del body["method"]
    r = await _rpc(client, agent["id"], body)
    assert r.json()["error"]["code"] == -32601


async def test_method_name_is_case_sensitive(client, a2a_on):
    agent = await _agent(client)
    body = _send("hi")
    body["method"] = "sendMessage"
    r = await _rpc(client, agent["id"], body)
    assert r.json()["error"]["code"] == -32601


@pytest.mark.parametrize(
    "params",
    [
        None,
        "text",
        [],
        {},
        {"message": None},
        {"message": "hello"},
        {"message": {"role": "ROLE_USER", "messageId": "m", "parts": []}},
        {"message": {"role": "ROLE_USER", "messageId": "m", "parts": "hello"}},
        {"message": {"role": "ROLE_USER", "messageId": "m", "parts": [{"text": "   \n"}]}},
        {"message": {"role": "ROLE_USER", "messageId": "m", "parts": [{"text": 42}]}},
        {"message": {"role": "ROLE_USER", "messageId": "m", "parts": ["just a string"]}},
    ],
)
async def test_every_shape_with_no_usable_text_is_invalid_params(client, a2a_on, params):
    agent = await _agent(client)
    body = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": params}
    r = await _rpc(client, agent["id"], body)
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32602, r.text
    # An invalid request must not have started a run or locked the agent.
    runs = (await client.get(f"/agents/{agent['id']}/runs")).json()
    assert runs == []
    assert (await client.get(f"/agents/{agent['id']}")).json()["is_running"] is False


async def test_a_null_id_and_a_string_id_are_echoed_back(client, a2a_on):
    agent = await _agent(client)
    for request_id in (None, "abc", 0):
        body = _send("hi")
        body["id"] = request_id
        r = await _rpc(client, agent["id"], body)
        assert r.json()["id"] == request_id, r.text
        assert "result" in r.json()


async def test_unknown_fields_in_the_envelope_are_ignored(client, a2a_on):
    agent = await _agent(client)
    body = _send("hi")
    body["extra"] = {"anything": True}
    body["params"]["configuration"] = {"blocking": True}
    body["params"]["message"]["metadata"] = {"k": "v"}
    r = await _rpc(client, agent["id"], body)
    assert r.json()["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


# --------------------------------------------------------------------------- A2A content


async def test_file_parts_are_dropped_and_text_parts_are_joined(client, a2a_on):
    agent = await _agent(client)
    body = _send("first")
    body["params"]["message"]["parts"] = [
        {"file": {"uri": "http://x/y.png"}},
        {"text": "first"},
        {"data": {"k": 1}},
        {"text": "second"},
    ]
    r = await _rpc(client, agent["id"], body)
    task = r.json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["history"][0]["parts"][0]["text"] == "first\nsecond"


async def test_unicode_and_emoji_survive_the_round_trip(client, a2a_on):
    agent = await _agent(client)
    text = "Résumé 日本語 🚀 \u0000 end"
    r = await _rpc(client, agent["id"], _send(text))
    task = r.json()["result"]["task"]
    assert task["history"][0]["parts"][0]["text"] == text
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"


async def test_a_200kb_message_is_accepted(client, a2a_on):
    agent = await _agent(client)
    r = await _rpc(client, agent["id"], _send("x" * 200_000))
    assert r.json()["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


async def test_context_id_is_echoed_and_otherwise_generated(client, a2a_on):
    agent = await _agent(client)
    r = await _rpc(client, agent["id"], _send("hi", contextId="ctx-77"))
    assert r.json()["result"]["task"]["contextId"] == "ctx-77"

    r = await _rpc(client, agent["id"], _send("hi"))
    generated = r.json()["result"]["task"]["contextId"]
    assert generated and generated != "ctx-77"


@pytest.mark.xfail(
    strict=True,
    reason="a2a/server.py:98-100 mints a fresh messageId instead of keeping the caller's",
)
async def test_history_keeps_the_callers_message_id(client, a2a_on):
    agent = await _agent(client)
    r = await _rpc(client, agent["id"], _send("hi"))
    assert r.json()["result"]["task"]["history"][0]["messageId"] == "m-1"


async def test_the_run_has_log_lines_readable_through_the_normal_api(client, a2a_on):
    agent = await _agent(client)
    r = await _rpc(client, agent["id"], _send("hi"))
    run_id = int(r.json()["result"]["task"]["id"].removeprefix("run-"))
    logs = (await client.get(f"/runs/{run_id}/logs")).json()
    assert len(logs) >= 2
    assert any("trigger=a2a" in row["line"] for row in logs)


# --------------------------------------------------------------------------- A2A auth


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer",
        "Bearer ",
        "Basic abc",
        "Token {token}",
        "Bearer {token}x",
        "Bearer x{token}",
        "Bearer {TOKEN_UPPER}",
    ],
)
async def test_every_wrong_authorization_shape_is_401(client, a2a_on, header):
    agent = await _agent(client)
    token = tokens.issue(agent["id"])
    value = header.format(token=token, TOKEN_UPPER=token.upper())
    r = await _rpc(client, agent["id"], _send("hi"), headers={"Authorization": value})
    assert r.status_code == 401, (header, r.text)
    assert r.json()["error"]["code"] == -32000
    assert r.json()["id"] is None
    assert (await client.get(f"/agents/{agent['id']}/runs")).json() == []


async def test_lowercase_scheme_and_padded_token_are_accepted(client, a2a_on):
    agent = await _agent(client)
    token = tokens.issue(agent["id"])
    for value in (f"bearer {token}", f"BEARER {token}", f"Bearer  {token} "):
        r = await _rpc(client, agent["id"], _send("hi"), headers={"Authorization": value})
        assert r.status_code == 200, (value, r.text)
        assert "result" in r.json()


async def test_auth_is_checked_before_the_body_is_parsed(client, a2a_on):
    agent = await _agent(client)
    r = await client.post(f"/a2a/agents/{agent['id']}", content=b"{not json")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == -32000


async def test_the_token_is_per_agent_and_stable_across_renames(client, a2a_on):
    agent = await _agent(client)
    before = (await client.get(f"/agents/{agent['id']}/deployment")).json()["a2a"]["token"]
    await client.patch(f"/agents/{agent['id']}", json={"name": "Renamed"})
    after = (await client.get(f"/agents/{agent['id']}/deployment")).json()["a2a"]["token"]
    assert before == after
    assert len(before) == 64


async def test_a_bearer_token_opens_an_agent_regardless_of_who_owns_it(client, session, a2a_on):
    """By design: A2A auth is the token, not the cookie. The token is the secret."""
    from app.models import Agent, User

    other = User(email="other@example.com")
    session.add(other)
    await session.commit()
    await session.refresh(other)
    theirs = Agent(user_id=other.id, name="Theirs", model="claude-sonnet-5", a2a_enabled=True)
    session.add(theirs)
    await session.commit()
    await session.refresh(theirs)

    assert (await client.get(f"/agents/{theirs.id}/deployment")).status_code == 404
    r = await _rpc(client, theirs.id, _send("hi"))
    assert r.status_code == 200
    assert r.json()["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


# --------------------------------------------------------------------------- A2A existence


async def test_an_agent_with_a2a_off_is_404_even_with_the_server_switch_on(client, a2a_on):
    agent = await _agent(client, a2a_enabled=False)
    assert agent["a2a_enabled"] is False
    assert (
        await client.get(f"/a2a/agents/{agent['id']}/.well-known/agent-card.json")
    ).status_code == 404
    assert (await _rpc(client, agent["id"], _send("hi"))).status_code == 404

    dep = (await client.get(f"/agents/{agent['id']}/deployment")).json()["a2a"]
    assert dep == {**dep, "enabled": False, "server_enabled": True, "agent_enabled": False}


async def test_the_agent_switch_can_be_flipped_by_patch(client, a2a_on):
    agent = await _agent(client, a2a_enabled=False)
    url = f"/a2a/agents/{agent['id']}/.well-known/agent-card.json"
    assert (await client.get(url)).status_code == 404

    r = await client.patch(f"/agents/{agent['id']}", json={"a2a_enabled": True})
    assert r.status_code == 200 and r.json()["a2a_enabled"] is True
    assert (await client.get(url)).status_code == 200

    # A patch that does not mention the switch leaves it alone.
    await client.patch(f"/agents/{agent['id']}", json={"name": "Renamed"})
    assert (await client.get(url)).status_code == 200

    await client.patch(f"/agents/{agent['id']}", json={"a2a_enabled": False})
    assert (await client.get(url)).status_code == 404


async def test_a2a_defaults_to_off_for_a_new_agent(client, a2a_on):
    r = await client.post("/agents", json={"name": "Plain", "model": "claude-sonnet-5"})
    assert r.json()["a2a_enabled"] is False


@pytest.mark.parametrize("agent_id", [0, -1, 999_999])
async def test_ids_that_exist_nowhere_are_404_on_both_routes(client, a2a_on, agent_id):
    assert (
        await client.get(f"/a2a/agents/{agent_id}/.well-known/agent-card.json")
    ).status_code == 404
    r = await _rpc(client, agent_id, _send("hi"))
    assert r.status_code == 404


async def test_a_non_integer_id_is_a_validation_error(client, a2a_on):
    r = await client.get("/a2a/agents/abc/.well-known/agent-card.json")
    assert r.status_code == 422


async def test_a_valid_token_is_still_404_while_a2a_is_off(client):
    agent = await _agent(client)
    assert settings.A2A_ENABLED is False
    r = await _rpc(client, agent["id"], _send("hi"))
    assert r.status_code == 404


async def test_the_card_and_endpoint_vanish_the_moment_the_agent_is_deleted(client, a2a_on):
    agent = await _agent(client)
    token = _auth(agent["id"])
    assert (await client.delete(f"/agents/{agent['id']}")).status_code == 204
    assert (
        await client.get(f"/a2a/agents/{agent['id']}/.well-known/agent-card.json")
    ).status_code == 404
    # 404 wins over 401: existence is not revealed even to a token holder.
    r = await client.post(f"/a2a/agents/{agent['id']}", json=_send("hi"), headers=token)
    assert r.status_code == 404


async def test_the_card_tracks_renames_and_tool_grants_live(client, a2a_on):
    agent = await _agent(client)
    url = f"/a2a/agents/{agent['id']}/.well-known/agent-card.json"
    assert (await client.get(url)).json()["name"] == "Daily Digest"

    r = await client.patch(
        f"/agents/{agent['id']}",
        json={"name": "Inbox Bot", "tools": [{"tool_name": "gmail.send", "can_write": True}]},
    )
    assert r.status_code == 200, r.text
    card = (await client.get(url)).json()
    assert card["name"] == "Inbox Bot"
    assert card["skills"][0]["name"] == "Inbox Bot"
    assert [s["id"] for s in card["skills"]] == ["run", "tool:gmail.send"]
    assert "read and write" in card["skills"][1]["description"]
    assert card["skills"][1]["tags"] == ["tool", "gmail"]


async def test_the_public_card_exposes_the_user_prompt_as_an_example(client, a2a_on):
    """Documents the security observation: the card route has no token."""
    agent = await _agent(client, user_prompt="Secret internal instructions")
    card = (await client.get(f"/a2a/agents/{agent['id']}/.well-known/agent-card.json")).json()
    assert card["skills"][0]["examples"] == ["Secret internal instructions"]


async def test_the_card_interface_url_uses_the_public_origin(client, a2a_on):
    before = settings.A2A_PUBLIC_URL
    settings.A2A_PUBLIC_URL = "https://relay.example.com/"
    try:
        agent = await _agent(client)
        card = (
            await client.get(f"/a2a/agents/{agent['id']}/.well-known/agent-card.json")
        ).json()
        assert card["supportedInterfaces"][0]["url"] == (
            f"https://relay.example.com/a2a/agents/{agent['id']}"
        )
        assert card["provider"]["url"] == "https://relay.example.com/"
    finally:
        settings.A2A_PUBLIC_URL = before


# --------------------------------------------------------------------------- A2A run outcomes


class _Exploding(ModelProvider):
    async def complete(self, **_: Any):
        raise RuntimeError("provider exploded")


class _Empty(ModelProvider):
    async def complete(self, **_: Any):
        from app.runtime.models_api import ModelTurn

        return ModelTurn(text="", input_tokens=1, output_tokens=0)


async def test_a_failing_run_is_a_failed_task_and_the_lock_is_released(
    client, a2a_on, one_attempt, monkeypatch
):
    monkeypatch.setattr(executor_module, "get_provider", lambda _model=None: _Exploding())
    agent = await _agent(client)

    r = await _rpc(client, agent["id"], _send("hi"))
    task = r.json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert task["artifacts"] == []
    assert "RuntimeError" in task["status"]["message"]["parts"][0]["text"]
    assert task["status"]["message"]["role"] == "ROLE_AGENT"
    assert task["status"]["timestamp"].endswith("Z")

    runs = (await client.get(f"/agents/{agent['id']}/runs")).json()
    assert runs[0]["status"] == "failed"
    assert (await client.get(f"/agents/{agent['id']}")).json()["is_running"] is False

    # And the agent can be called again straight away.
    monkeypatch.setattr(executor_module, "get_provider", lambda _model=None: _Empty())
    r = await _rpc(client, agent["id"], _send("hi"))
    assert r.status_code == 200
    assert "result" in r.json()


async def test_a_failure_produces_a_notification_like_any_other_run(
    client, a2a_on, one_attempt, monkeypatch
):
    monkeypatch.setattr(executor_module, "get_provider", lambda _model=None: _Exploding())
    from app.runtime import bus

    agent = await _agent(client)
    await _rpc(client, agent["id"], _send("hi"))
    # The outcome is handed to the notifier's queue; the notifier process writes the row.
    queued = await bus.pop(settings.NOTIFY_QUEUE, timeout=1)
    assert queued is not None
    assert queued["kind"] == "failure"
    assert queued["title"] == "Daily Digest failed"


async def test_a_busy_agent_is_refused_without_creating_a_run(client, session, a2a_on):
    from app.models import Agent

    agent = await _agent(client)
    row = await session.get(Agent, agent["id"])
    row.is_running = True
    await session.commit()

    r = await _rpc(client, agent["id"], _send("hi"))
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32004
    assert (await client.get(f"/agents/{agent['id']}/runs")).json() == []

    row.is_running = False
    await session.commit()
    r = await _rpc(client, agent["id"], _send("hi"))
    assert "result" in r.json()


async def test_two_concurrent_calls_yield_one_run_and_one_busy_error(client, a2a_on, monkeypatch):
    class _Slow(ModelProvider):
        async def complete(self, **_: Any):
            from app.runtime.models_api import ModelTurn

            await asyncio.sleep(0.3)
            return ModelTurn(text="ok", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(executor_module, "get_provider", lambda _model=None: _Slow())
    agent = await _agent(client)

    a, b = await asyncio.gather(
        _rpc(client, agent["id"], _send("one")),
        _rpc(client, agent["id"], _send("two")),
    )
    bodies = [a.json(), b.json()]
    ok = [x for x in bodies if "result" in x]
    busy = [x for x in bodies if x.get("error", {}).get("code") == -32004]
    assert len(ok) == 1 and len(busy) == 1, bodies
    assert len((await client.get(f"/agents/{agent['id']}/runs")).json()) == 1


async def test_a2a_and_run_now_share_the_same_lock(client, a2a_on, monkeypatch):
    class _Slow(ModelProvider):
        async def complete(self, **_: Any):
            from app.runtime.models_api import ModelTurn

            await asyncio.sleep(0.3)
            return ModelTurn(text="ok", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(executor_module, "get_provider", lambda _model=None: _Slow())
    agent = await _agent(client)

    a2a_task = asyncio.create_task(_rpc(client, agent["id"], _send("one")))
    await asyncio.sleep(0.05)
    run_now = await client.post(f"/agents/{agent['id']}/run")
    assert run_now.status_code == 409
    r = await a2a_task
    assert r.json()["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


async def test_a_paused_agent_still_answers_a2a_calls(client, a2a_on):
    """Pause stops the schedule only. Documented so the behaviour is deliberate."""
    agent = await _agent(client, schedule={"cron": "0 9 * * *", "timezone": "UTC"})
    assert (await client.post(f"/agents/{agent['id']}/pause")).status_code == 200
    r = await _rpc(client, agent["id"], _send("hi"))
    assert r.json()["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


# --------------------------------------------------------------------------- Jenkins


class FakeJenkins:
    """A scriptable Jenkins. Each knob mirrors one thing the real server can do."""

    def __init__(self) -> None:
        self.crumb_status = 200
        self.trigger_status = 201
        self.trigger_location = "http://jenkins/queue/item/5/"
        self.queue_polls_until_executable = 0
        self.queue_cancelled = False
        self.queue_body_is_html = False
        self.job_status = 200
        self.job_body_is_html = False
        self.builds: list[dict[str, Any]] = []
        self.raise_error: Exception | None = None
        self.requests: list[httpx.Request] = []
        self._polls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_error is not None:
            raise self.raise_error
        path = request.url.path

        if path.endswith("/crumbIssuer/api/json"):
            if self.crumb_status != 200:
                return httpx.Response(self.crumb_status, text="<html>no</html>")
            return httpx.Response(200, json={"crumbRequestField": "Jenkins-Crumb", "crumb": "c1"})

        if path.endswith("/buildWithParameters"):
            headers = {"Location": self.trigger_location} if self.trigger_location else {}
            return httpx.Response(self.trigger_status, headers=headers, text="")

        if "/queue/item/" in path:
            if self.queue_body_is_html:
                return httpx.Response(200, text="<html>login</html>")
            self._polls += 1
            if self.queue_cancelled:
                return httpx.Response(200, json={"cancelled": True})
            if self._polls > self.queue_polls_until_executable:
                return httpx.Response(
                    200,
                    json={"executable": {"number": 42, "url": "http://jenkins/job/x/42/"}},
                )
            return httpx.Response(200, json={"why": "Waiting for next available executor"})

        if "/job/" in path and path.endswith("/api/json"):
            if self.job_status != 200:
                return httpx.Response(self.job_status, text="")
            if self.job_body_is_html:
                return httpx.Response(200, text="<html>login</html>")
            return httpx.Response(200, json={"builds": self.builds})

        return httpx.Response(404, text="")


@pytest.fixture
def fake_jenkins(monkeypatch):
    fake = FakeJenkins()
    real_client = httpx.AsyncClient

    def patched(**kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=MockTransport(fake.handler), **kwargs)

    monkeypatch.setattr(jenkins.httpx, "AsyncClient", patched)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(jenkins.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(settings, "JENKINS_ENABLED", True)
    yield fake


def _build(agent_id: int, number: int, *, building=False, result="SUCCESS") -> dict:
    return {
        "number": number,
        "building": building,
        "result": None if building else result,
        "url": f"http://jenkins/job/agent-create/{number}/",
        "actions": [{"parameters": [{"name": "AGENT_ID", "value": str(agent_id)}]}],
    }


async def test_create_posts_the_six_parameters_and_does_not_wait(client, fake_jenkins):
    agent = await _agent(client, name="Daily Digest!")
    posts = [r for r in fake_jenkins.requests if r.method == "POST"]
    assert len(posts) == 1
    assert posts[0].url.path.endswith("/job/agent-create/buildWithParameters")
    params = dict(posts[0].url.params)
    assert params == {
        "AGENT_ID": str(agent["id"]),
        "AGENT_SLUG": f"daily-digest-{agent['id']}",
        "AGENT_NAME": "Daily Digest!",
        "HOST_IP": settings.AGENT_HOST_IP,
        "HOST_DOMAIN": settings.AGENT_HOST_DOMAIN,
        "HOSTS_FILE": settings.AGENT_HOSTS_FILE,
    }
    assert posts[0].headers.get("Jenkins-Crumb") == "c1"
    # No queue polling for a create.
    assert not any("/queue/item/" in r.url.path for r in fake_jenkins.requests)


async def test_delete_fires_the_delete_job_with_the_same_slug(client, fake_jenkins):
    agent = await _agent(client)
    fake_jenkins.requests.clear()
    assert (await client.delete(f"/agents/{agent['id']}")).status_code == 204
    posts = [r for r in fake_jenkins.requests if r.method == "POST"]
    assert posts[0].url.path.endswith("/job/agent-delete/buildWithParameters")
    assert dict(posts[0].url.params)["AGENT_SLUG"] == f"daily-digest-{agent['id']}"


async def test_jenkins_down_never_blocks_create_deploy_or_delete(client, fake_jenkins):
    fake_jenkins.raise_error = httpx.ConnectError("refused")
    agent = await _agent(client)
    dep = (await client.get(f"/agents/{agent['id']}/deployment")).json()
    assert dep["enabled"] is True
    assert {j["status"] for j in dep["jobs"]} == {"unavailable"}
    assert dep["jobs"][0]["message"] == "Jenkins is not reachable"

    r = await client.post(f"/agents/{agent['id']}/deploy")
    assert r.status_code == 200
    assert r.json()["jobs"][0]["status"] == "unavailable"
    assert (await client.delete(f"/agents/{agent['id']}")).status_code == 204


async def test_a_jenkins_timeout_is_reported_as_unavailable(client, fake_jenkins):
    fake_jenkins.raise_error = httpx.ReadTimeout("slow")
    agent = await _agent(client)
    r = await client.post(f"/agents/{agent['id']}/deploy")
    assert r.json()["jobs"][0]["status"] == "unavailable"


async def test_a_refused_crumb_still_posts_the_build(client, fake_jenkins):
    fake_jenkins.crumb_status = 403
    agent = await _agent(client)
    r = await client.post(f"/agents/{agent['id']}/deploy")
    assert r.json()["jobs"][0]["status"] == "running"
    posts = [r for r in fake_jenkins.requests if r.method == "POST"]
    assert "Jenkins-Crumb" not in posts[-1].headers
    assert agent["id"]


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_a_refused_trigger_is_a_failure_with_the_status_in_the_message(
    client, fake_jenkins, status
):
    fake_jenkins.trigger_status = status
    agent = await _agent(client)
    job = (await client.post(f"/agents/{agent['id']}/deploy")).json()["jobs"][0]
    assert job["status"] == "failure"
    assert job["message"] == f"Jenkins returned {status}"
    assert job["build_number"] is None


async def test_deploy_returns_the_build_number_once_an_executor_picks_it_up(client, fake_jenkins):
    fake_jenkins.queue_polls_until_executable = 3
    agent = await _agent(client)
    job = (await client.post(f"/agents/{agent['id']}/deploy")).json()["jobs"][0]
    assert job == {
        "job": "agent-deploy",
        "status": "running",
        "build_number": 42,
        "url": "http://jenkins/job/x/42/",
        "message": "Started",
    }


async def test_deploy_gives_up_waiting_after_twenty_polls(client, fake_jenkins):
    fake_jenkins.queue_polls_until_executable = 100
    agent = await _agent(client)
    job = (await client.post(f"/agents/{agent['id']}/deploy")).json()["jobs"][0]
    assert job["status"] == "queued"
    assert job["message"] == "Waiting for an executor"
    assert sum("/queue/item/" in r.url.path for r in fake_jenkins.requests) == 20


async def test_a_cancelled_queue_item_is_reported_as_queued(client, fake_jenkins):
    fake_jenkins.queue_cancelled = True
    agent = await _agent(client)
    job = (await client.post(f"/agents/{agent['id']}/deploy")).json()["jobs"][0]
    assert job["status"] == "queued"


async def test_a_trigger_with_no_location_header_is_queued(client, fake_jenkins):
    fake_jenkins.trigger_location = ""
    agent = await _agent(client)
    job = (await client.post(f"/agents/{agent['id']}/deploy")).json()["jobs"][0]
    assert job["status"] == "queued"
    assert job["message"] == "Queued"


async def test_deployment_lists_the_latest_build_per_job_for_this_agent_only(
    client, fake_jenkins
):
    agent = await _agent(client)
    other_id = agent["id"] + 100
    fake_jenkins.builds = [
        _build(other_id, 9, building=True),
        _build(agent["id"], 8, building=True),
        _build(agent["id"], 7, result="FAILURE"),
    ]
    dep = (await client.get(f"/agents/{agent['id']}/deployment")).json()
    create = dep["jobs"][0]
    assert (create["status"], create["build_number"]) == ("running", 8)


@pytest.mark.parametrize(
    ("result", "expected"),
    [("SUCCESS", "success"), ("FAILURE", "failure"), ("ABORTED", "failure"), ("UNSTABLE", "failure")],
)
async def test_every_jenkins_result_maps_to_a_status(client, fake_jenkins, result, expected):
    agent = await _agent(client)
    fake_jenkins.builds = [_build(agent["id"], 1, result=result)]
    dep = (await client.get(f"/agents/{agent['id']}/deployment")).json()
    assert dep["jobs"][0]["status"] == expected


async def test_a_build_with_an_integer_agent_id_parameter_still_matches(client, fake_jenkins):
    agent = await _agent(client)
    build = _build(agent["id"], 3)
    build["actions"][0]["parameters"][0]["value"] = agent["id"]
    fake_jenkins.builds = [build]
    dep = (await client.get(f"/agents/{agent['id']}/deployment")).json()
    assert dep["jobs"][0]["build_number"] == 3


async def test_a_build_with_odd_action_shapes_does_not_crash(client, fake_jenkins):
    agent = await _agent(client)
    fake_jenkins.builds = [
        {"number": 1, "actions": [None, "x", {}, {"parameters": None}, {"parameters": [None]}]},
        {"number": 2, "actions": None},
        _build(agent["id"], 3),
    ]
    dep = (await client.get(f"/agents/{agent['id']}/deployment")).json()
    assert dep["jobs"][0]["build_number"] == 3


async def test_a_missing_job_is_unavailable_and_the_others_still_answer(client, fake_jenkins):
    fake_jenkins.job_status = 404
    agent = await _agent(client)
    dep = (await client.get(f"/agents/{agent['id']}/deployment")).json()
    assert [j["status"] for j in dep["jobs"]] == ["unavailable"] * 3
    assert dep["jobs"][0]["message"] == "No such job"


@pytest.mark.xfail(
    strict=True,
    reason="cicd/jenkins.py:211 calls response.json() outside the except; HTML becomes a 500",
)
async def test_an_html_login_page_instead_of_job_json_is_handled(client, fake_jenkins):
    """A logged-out Jenkins answers 200 with HTML. That must not become a 500."""
    fake_jenkins.job_body_is_html = True
    agent = await _agent(client)
    r = await client.get(f"/agents/{agent['id']}/deployment")
    assert r.status_code == 200, r.text
    assert {j["status"] for j in r.json()["jobs"]} <= {"unavailable", "failure", "none"}


@pytest.mark.xfail(
    strict=True,
    reason="cicd/jenkins.py:105 calls response.json() outside the except; HTML becomes a 500",
)
async def test_an_html_page_instead_of_queue_json_is_handled(client, fake_jenkins):
    fake_jenkins.queue_body_is_html = True
    agent = await _agent(client)
    r = await client.post(f"/agents/{agent['id']}/deploy")
    assert r.status_code == 200, r.text
    assert r.json()["jobs"][0]["status"] in {"queued", "unavailable", "failure"}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Daily Digest", "daily-digest"),
        ("  spaced   out  ", "spaced-out"),
        ("UPPER", "upper"),
        ("Résumé Bot", "r-sum-bot"),
        ("日本語", "agent"),
        ("a" * 80, "a" * 40),
        ("-" * 10 + "x" + "-" * 10, "x"),
        ("1234", "1234"),
        ("a.b_c/d", "a-b-c-d"),
    ],
)
def test_slug_edge_cases(name, expected):
    assert jenkins.agent_slug(9, name) == f"{expected}-9"


@pytest.mark.xfail(
    strict=True,
    reason="cicd/jenkins.py:46 trims edges before the 40-char cut, so a cut can leave '-' at the end",
)
def test_slug_for_a_long_name_has_no_trailing_hyphen_before_the_id():
    slug = jenkins.agent_slug(9, "a" * 39 + "-b")
    assert "--" not in slug
    assert slug.endswith("-9")
