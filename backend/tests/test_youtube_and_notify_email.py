import httpx
import pytest

from app.config import settings
from app.connectors import http_client
from app.connectors.base import ConnectionMissing
from app.connectors.youtube import YouTubeConnector, video_id_from
from app.security import oauth


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_STUBS", False)
    yield
    http_client.transport = None


def test_video_ids_are_pulled_out_of_urls():
    assert video_id_from("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1") == "dQw4w9WgXcQ"
    assert video_id_from("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert video_id_from("dQw4w9WgXcQ") == "dQw4w9WgXcQ"


async def test_video_info_uses_the_key_and_shapes_the_answer(live, monkeypatch):
    monkeypatch.setattr(settings, "YOUTUBE_API_KEY", "env-key")

    def handler(request):
        assert request.url.host == "www.googleapis.com" and request.url.params["key"] == "env-key"
        assert request.url.params["id"] == "dQw4w9WgXcQ"
        return httpx.Response(200, json={"items": [{"id": "dQw4w9WgXcQ",
            "snippet": {"title": "T", "channelTitle": "C", "publishedAt": "2009-10-25T06:57:33Z"},
            "statistics": {"viewCount": "1500000000", "likeCount": "17000000"},
            "contentDetails": {"duration": "PT3M33S"}}]})

    http_client.transport = httpx.MockTransport(handler)
    out = await YouTubeConnector().video_info(credential=None, video="https://youtu.be/dQw4w9WgXcQ")
    assert out["title"] == "T" and out["views"] == 1500000000 and out["duration"] == "PT3M33S"


async def test_a_pasted_key_beats_the_env_key(live, monkeypatch):
    monkeypatch.setattr(settings, "YOUTUBE_API_KEY", "env-key")
    seen = {}
    http_client.transport = httpx.MockTransport(
        lambda r: (seen.update(key=r.url.params["key"]), httpx.Response(200, json={"items": []}))[1]
    )
    await YouTubeConnector().search(credential="pasted", q="x")
    assert seen["key"] == "pasted"


async def test_no_key_anywhere_is_connection_missing(live, monkeypatch):
    monkeypatch.setattr(settings, "YOUTUBE_API_KEY", "")
    with pytest.raises(ConnectionMissing):
        await YouTubeConnector().search(credential=None, q="x")


def test_google_redirect_can_be_overridden(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://localhost:9999/cb")
    assert oauth.redirect_uri("gmail") == "http://localhost:9999/cb"
    assert oauth.redirect_uri("slack").endswith("/connections/oauth/slack/callback")


async def test_email_via_gmail_goes_through_the_users_connection(session, user, live, monkeypatch):
    from app.models import Connection, Credential
    from app.notify import channels
    from app.security.crypto import encrypt

    monkeypatch.setattr(settings, "EMAIL_SENDER", "gmail")
    assert await channels.send_email("a@b.c", "S", "B", session=session, user_id=user.id) is False

    cred = Credential(ciphertext=encrypt("tok")); session.add(cred); await session.commit(); await session.refresh(cred)
    session.add(Connection(user_id=user.id, kind="oauth", provider="gmail", label="g", status="connected",
                           credential_id=cred.id, config_json={})); await session.commit()
    seen = {}

    def handler(request):
        seen["path"] = request.url.path; seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"id": "m1"})

    http_client.transport = httpx.MockTransport(handler)
    assert await channels.send_email("a@b.c", "S", "B", session=session, user_id=user.id) is True
    assert seen["path"].endswith("/messages/send") and seen["auth"] == "Bearer tok"


async def test_notify_email_redirects_delivery(session, user, monkeypatch):
    from app.notify import channels, dispatcher

    monkeypatch.setattr(settings, "NOTIFY_EMAIL", "me@example.com")
    seen = {}

    async def fake_email(to, subject, body, **kw):
        seen["to"] = to; return True
    monkeypatch.setattr(channels, "send_email", fake_email)
    await dispatcher.deliver(session, {"user_id": user.id, "kind": "success", "title": "t", "body": ""})
    assert seen["to"] == "me@example.com"
