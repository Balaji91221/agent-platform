"""Sign in with Google: session cookie, /auth/me, demo-user claim, logout, 401s."""

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.connectors import http_client
from app.main import app
from app.security import session as tokens


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setattr(settings, "AUTH_MODE", "google")
    yield
    http_client.transport = None


def _google_mock(identity: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            form = dict(p.split("=") for p in request.content.decode().split("&"))
            assert form["grant_type"] == "authorization_code" and form["code"] == "c0de"
            assert "auth%2Fgoogle%2Fcallback" in form["redirect_uri"]
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3599, "id_token": "x"})
        assert request.url.host == "openidconnect.googleapis.com"
        assert request.headers["authorization"] == "Bearer at"
        return httpx.Response(200, json=identity)
    http_client.transport = httpx.MockTransport(handler)


def test_session_tokens_round_trip_and_reject_forgery_and_expiry():
    tok = tokens.issue(7)
    assert tokens.verify(tok) == 7
    assert tokens.verify(tok[:-1] + ("0" if tok[-1] != "0" else "1")) is None
    assert tokens.verify(tokens.issue(7, ttl_seconds=-1)) is None
    assert tokens.verify(None) is None and tokens.verify("garbage") is None


async def test_google_mode_rejects_header_and_no_cookie(session, user, google):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/auth/me")).status_code == 401
        assert (await c.get("/agents", headers={"X-User-Id": str(user.id)})).status_code == 401
        c.cookies.set(settings.SESSION_COOKIE, tokens.issue(user.id))
        me = await c.get("/auth/me")
    assert me.status_code == 200 and me.json()["email"] == user.email


async def test_start_redirects_to_google_with_identity_scopes(google):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/auth/google/start")
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/") and "scope=openid+email+profile" in loc
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fauth%2Fgoogle%2Fcallback" in loc


async def test_first_login_claims_the_demo_user_and_sets_the_cookie(session, google):
    from sqlalchemy import select

    from app.dependencies.auth import DEMO_EMAIL
    from app.models import Agent, User

    demo = User(email=DEMO_EMAIL); session.add(demo); await session.commit(); await session.refresh(demo)
    session.add(Agent(user_id=demo.id, name="Kept", model="claude-sonnet-5")); await session.commit()
    _google_mock({"sub": "g-1", "email": "Me@Example.com", "email_verified": True,
                  "name": "Me Person", "picture": "https://p/x.png"})

    from app.security import oauth
    state = oauth.make_state(0, "google_login")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/auth/google/callback?code=c0de&state={state}")
        assert r.status_code == 303 and r.headers["location"] == "http://localhost:3100/today"
        assert settings.SESSION_COOKIE in r.cookies
        me = await c.get("/auth/me")
        agents = await c.get("/agents")
    assert me.json() == {"id": demo.id, "email": "me@example.com", "name": "Me Person", "picture": "https://p/x.png"}
    assert [a["name"] for a in agents.json()] == ["Kept"], "the demo workspace was claimed, not abandoned"
    session.expire_all()  # the app wrote through its own session
    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1 and users[0].google_sub == "g-1"


async def test_second_account_gets_its_own_empty_workspace(session, google):
    from app.models import User

    session.add(User(email="first@example.com", google_sub="g-first")); await session.commit()
    _google_mock({"sub": "g-2", "email": "second@example.com", "email_verified": True, "name": "Two"})
    from app.security import oauth
    state = oauth.make_state(0, "google_login")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.get(f"/auth/google/callback?code=c0de&state={state}")
        me = (await c.get("/auth/me")).json()
        agents = (await c.get("/agents")).json()
    assert me["email"] == "second@example.com" and agents == []


async def test_bad_state_and_logout(session, user, google):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/auth/google/callback?code=x&state=bad")
        assert r.status_code == 303 and "/login?error=" in r.headers["location"]
        c.cookies.set(settings.SESSION_COOKIE, tokens.issue(user.id))
        assert (await c.get("/auth/me")).status_code == 200
        out = await c.post("/auth/logout")
        assert out.status_code == 204
        c.cookies.clear()
        assert (await c.get("/auth/me")).status_code == 401


async def test_unconfigured_start_is_422(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/auth/google/start")
    assert r.status_code == 422 and "GOOGLE_CLIENT_ID" in r.text


async def test_demo_mode_still_works_without_a_cookie(session, user):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/auth/me", headers={"X-User-Id": str(user.id)})
    assert r.status_code == 200 and r.json()["email"] == user.email


async def test_catalogues_need_a_session_in_google_mode(session, user, google):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/models")).status_code == 401
        assert (await c.get("/connections/tools")).status_code == 401
        c.cookies.set(settings.SESSION_COOKIE, tokens.issue(user.id))
        assert (await c.get("/models")).status_code == 200
        assert (await c.get("/connections/tools")).status_code == 200
