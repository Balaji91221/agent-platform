"""The live connector path: real request shapes, no sample data, honest failures.

Every test here turns CONNECTOR_STUBS off and routes httpx through a
MockTransport that asserts the URL, the auth header, and the body.
"""

from __future__ import annotations

import base64
import json
from datetime import timedelta

import httpx
import pytest

from app.config import settings
from app.connectors import http_client
from app.connectors.base import ConnectionMissing, ConnectorError
from app.connectors.gmail import GmailConnector, build_raw_email
from app.connectors.slack import SlackConnector
from app.models import Agent, AgentTool, Connection, Credential, as_utc, utcnow
from app.runtime import router
from app.security import oauth
from app.security.crypto import decrypt, encrypt
from app.security.secrets import access_token, dump_secret, parse_secret
from app.security.tokens import usable_secret


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_STUBS", False)
    yield
    http_client.transport = None


def _mock(handler):
    http_client.transport = httpx.MockTransport(handler)


async def _connected(session, user, provider, secret="tok-123", **cred_kw) -> Connection:
    cred = Credential(ciphertext=encrypt(secret), **cred_kw)
    session.add(cred); await session.commit(); await session.refresh(cred)
    conn = Connection(user_id=user.id, kind="oauth", provider=provider, label=provider,
                      status="connected", credential_id=cred.id, config_json={})
    session.add(conn); await session.commit(); await session.refresh(conn)
    return conn


# ---------------------------------------------------------------- secrets
def test_parse_secret_accepts_raw_and_json():
    assert parse_secret("abc") == {"access_token": "abc"}
    blob = dump_secret("at", "rt", None)
    assert parse_secret(blob)["refresh_token"] == "rt" and access_token(blob) == "at"
    assert parse_secret("{not json") == {"access_token": "{not json"}


# ---------------------------------------------------------------- gmail
async def test_gmail_list_unread_hits_the_real_api_with_the_bearer_token(live):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["authorization"] == "Bearer tok-123"
        if request.url.path.endswith("/messages"):
            assert request.url.params["q"] == "is:unread after:2026/09/01"
            return httpx.Response(200, json={"messages": [{"id": "m1"}], "resultSizeEstimate": 1})
        return httpx.Response(200, json={"payload": {"headers": [
            {"name": "From", "value": "a@x.com"}, {"name": "Subject", "value": "Hi"},
            {"name": "Date", "value": "Mon"}]}})

    _mock(handler)
    out = await GmailConnector().list_unread(credential="tok-123", since="2026/09/01")
    assert out == {"count": 1, "senders": 1,
                   "messages": [{"id": "m1", "from": "a@x.com", "subject": "Hi", "date": "Mon"}]}
    assert seen[0].url.host == "gmail.googleapis.com"


async def test_gmail_without_a_connection_raises_not_sample_data(live):
    with pytest.raises(ConnectionMissing, match="Gmail is not connected"):
        await GmailConnector().list_unread(credential=None)


async def test_gmail_api_errors_are_readable(live):
    _mock(lambda r: httpx.Response(401, json={"error": {"message": "Invalid Credentials"}}))
    with pytest.raises(ConnectorError, match="Gmail 401: Invalid Credentials"):
        await GmailConnector().read_message(credential="bad", id="m1")


async def test_gmail_send_posts_a_base64url_rfc2822_message(live):
    body = {}

    def handler(request):
        assert request.url.path.endswith("/messages/send")
        body.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "sent-1"})

    _mock(handler)
    out = await GmailConnector().send(credential="tok", to="b@y.com", subject="S", body="hello")
    assert out == {"sent": True, "to": "b@y.com", "id": "sent-1"}
    raw = base64.urlsafe_b64decode(body["raw"] + "==").decode()
    assert "To: b@y.com" in raw and "Subject: S" in raw and "hello" in raw
    assert build_raw_email("a", "b", "c")  # pure helper stays importable


# ---------------------------------------------------------------- slack
async def test_slack_post_message_uses_chat_postmessage(live):
    def handler(request):
        assert request.url == "https://slack.com/api/chat.postMessage"
        assert request.headers["authorization"] == "Bearer xoxb-1"
        assert json.loads(request.content) == {"channel": "#daily", "text": "hi"}
        return httpx.Response(200, json={"ok": True, "channel": "C1", "ts": "1.2"})

    _mock(handler)
    out = await SlackConnector().post_message(credential="xoxb-1", channel="#daily", text="hi")
    assert out == {"ok": True, "channel": "C1", "ts": "1.2"}


async def test_slack_ok_false_becomes_a_connector_error(live):
    _mock(lambda r: httpx.Response(200, json={"ok": False, "error": "channel_not_found"}))
    with pytest.raises(ConnectorError, match="channel_not_found"):
        await SlackConnector().post_message(credential="x", channel="#nope", text="hi")


async def test_slack_read_channel_resolves_a_name_to_an_id(live):
    def handler(request):
        if request.url.path.endswith("conversations.list"):
            return httpx.Response(200, json={"ok": True, "channels": [{"id": "C9", "name": "daily"}]})
        assert request.url.params["channel"] == "C9"
        return httpx.Response(200, json={"ok": True, "messages": [{"user": "U1", "text": "yo", "ts": "1"}]})

    _mock(handler)
    out = await SlackConnector().read_channel(credential="x", channel="#daily", limit=5)
    assert out["channel"] == "C9" and out["messages"][0]["text"] == "yo"


# ---------------------------------------------------------------- router + team
async def test_router_blocks_a_tool_whose_provider_was_never_connected(session, user, live):
    agent = Agent(user_id=user.id, name="A", model="claude-sonnet-5")
    session.add(agent); await session.commit(); await session.refresh(agent)
    session.add(AgentTool(agent_id=agent.id, tool_name="gmail.list_unread")); await session.commit()

    with pytest.raises(ConnectionMissing, match="gmail is not connected"):
        await router.call(session, user_id=user.id, tool_name="gmail.list_unread",
                          arguments={}, can_write={})


async def test_router_decrypts_and_passes_the_token_through(session, user, live):
    await _connected(session, user, "slack", secret=dump_secret("xoxb-9", None, None))
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"ok": True, "channels": []})

    _mock(handler)
    await router.call(session, user_id=user.id, tool_name="slack.list_channels",
                      arguments={}, can_write={})
    assert seen["auth"] == "Bearer xoxb-9"


async def test_team_blocks_a_mate_whose_provider_is_missing(session, user, live):
    from app.models import Team, Teammate
    from app.team.router import _blocked_reason

    agent = Agent(user_id=user.id, name="Mailer", model="claude-sonnet-5")
    session.add(agent); await session.commit(); await session.refresh(agent)
    session.add(AgentTool(agent_id=agent.id, tool_name="gmail.list_unread"))
    team = Team(user_id=user.id); session.add(team); await session.commit(); await session.refresh(team)
    mate = Teammate(team_id=team.id, agent_id=agent.id, display_name="mailer", job_title="Mail")
    session.add(mate); await session.commit(); await session.refresh(mate)

    assert (await _blocked_reason(session, mate)) == "gmail is not connected — connect it on the Connections screen"
    await _connected(session, user, "gmail")
    assert await _blocked_reason(session, mate) is None


# ---------------------------------------------------------------- oauth
def test_unconfigured_provider_refuses_to_start_naming_the_env_vars():
    with pytest.raises(oauth.OAuthNotConfigured, match="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET"):
        oauth.authorize_url("gmail", user_id=1)
    assert not oauth.is_configured("slack")


def test_state_round_trips_and_rejects_tampering():
    state = oauth.make_state(7, "gmail")
    assert oauth.verify_state(state, "gmail") == 7
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(state, "slack")
    with pytest.raises(oauth.OAuthError):
        oauth.verify_state(state[:-1] + ("0" if state[-1] != "0" else "1"), "gmail")


async def test_configured_provider_builds_a_real_authorize_url_and_exchanges_the_code(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "sec")
    url = oauth.authorize_url("gmail", user_id=3)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?client_id=cid")
    assert "gmail.readonly" in url and "access_type=offline" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fconnections%2Foauth%2Fgmail%2Fcallback" in url

    def handler(request):
        assert request.url == "https://oauth2.googleapis.com/token"
        form = dict(p.split("=") for p in request.content.decode().split("&"))
        assert form["grant_type"] == "authorization_code" and form["code"] == "c0de"
        return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3599})

    http_client.transport = httpx.MockTransport(handler)
    try:
        tokens = await oauth.exchange_code("gmail", "c0de")
    finally:
        http_client.transport = None
    assert tokens == oauth.TokenSet("at", "rt", 3599)


async def test_callback_stores_tokens_and_bounces_to_the_frontend(session, user, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    monkeypatch.setattr(settings, "SLACK_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "SLACK_CLIENT_SECRET", "sec")
    http_client.transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"ok": True, "access_token": "xoxb-new"})
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            start = await c.get("/connections/oauth/slack/start", headers={"X-User-Id": str(user.id)})
            assert start.status_code == 200
            state = httpx.URL(start.json()["authorize_url"]).params["state"]
            done = await c.get(f"/connections/oauth/slack/callback?code=abc&state={state}")
    finally:
        http_client.transport = None
    assert done.status_code == 303
    assert done.headers["location"] == "http://localhost:3100/connections?connected=slack"

    from sqlalchemy import select
    conn = (await session.execute(select(Connection).where(Connection.provider == "slack"))).scalars().one()
    cred = await session.get(Credential, conn.credential_id)
    assert access_token(decrypt(cred.ciphertext)) == "xoxb-new" and conn.status == "connected"


async def test_callback_with_a_bad_state_never_stores_anything(session, user):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import func, select

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        done = await c.get("/connections/oauth/gmail/callback?code=abc&state=garbage")
    assert done.status_code == 303 and "oauth_error=" in done.headers["location"]
    assert (await session.execute(select(func.count()).select_from(Connection))).scalar() == 0


async def test_unconfigured_start_is_a_422(user):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/connections/oauth/gmail/start", headers={"X-User-Id": str(user.id)})
    assert r.status_code == 422 and "GOOGLE_CLIENT_ID" in r.text


# ---------------------------------------------------------------- refresh
async def test_an_expiring_token_is_refreshed_through_the_provider(session, user, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "sec")
    conn = await _connected(session, user, "gmail", secret=dump_secret("old", "rt-1", None),
                            expires_at=utcnow() + timedelta(seconds=30))

    def handler(request):
        form = dict(p.split("=") for p in request.content.decode().split("&"))
        assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "rt-1"
        return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})

    http_client.transport = httpx.MockTransport(handler)
    try:
        secret = await usable_secret(session, conn)
    finally:
        http_client.transport = None
    parsed = parse_secret(secret)
    assert parsed["access_token"] == "new" and parsed["refresh_token"] == "rt-1"
    cred = await session.get(Credential, conn.credential_id)
    assert as_utc(cred.expires_at) > utcnow() + timedelta(minutes=50)


# ---------------------------------------------------------------- notify
async def test_slack_dm_looks_up_the_member_by_email_then_dms_the_id(session, user, live):
    from app.notify import channels

    assert await channels.send_slack_dm(session, user.id, user.email, "hi") is False  # not connected
    await _connected(session, user, "slack", secret="xoxb-dm")
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("users.lookupByEmail"):
            assert request.url.params["email"] == "test@example.com"
            return httpx.Response(200, json={"ok": True, "user": {"id": "U42"}})
        assert json.loads(request.content) == {"channel": "U42", "text": "hi"}
        return httpx.Response(200, json={"ok": True, "channel": "D1", "ts": "1"})

    _mock(handler)
    assert await channels.send_slack_dm(session, user.id, user.email, "hi") is True
    assert [r.headers["authorization"] for r in seen] == ["Bearer xoxb-dm"] * 2


async def test_slack_dm_failure_is_false_not_a_crash(session, user, live):
    from app.notify import channels

    await _connected(session, user, "slack", secret="xoxb-dm")
    _mock(lambda r: httpx.Response(200, json={"ok": False, "error": "users_not_found"}))
    assert await channels.send_slack_dm(session, user.id, user.email, "hi") is False


async def test_smtp_sender_builds_the_message_and_console_still_works(monkeypatch):
    from app.notify import channels

    assert await channels.send_email("a@b.c", "S", "B") is True  # console default
    monkeypatch.setattr(settings, "EMAIL_SENDER", "smtp")
    assert await channels.send_email("a@b.c", "S", "B") is False  # no host -> honest False

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
    sent = {}
    monkeypatch.setattr(channels, "_smtp_send", lambda msg: sent.update(to=msg["To"], subject=msg["Subject"]))
    assert await channels.send_email("a@b.c", "S", "B") is True
    assert sent == {"to": "a@b.c", "subject": "S"}
