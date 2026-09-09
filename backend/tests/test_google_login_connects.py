"""Sign in with Google also connects Gmail and Sheets when those scopes are granted."""

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.connectors import http_client
from app.connectors.sheets import SheetsConnector, spreadsheet_id_from
from app.main import app
from app.security import oauth

GMAIL = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"
SHEETS = "https://www.googleapis.com/auth/spreadsheets"


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setattr(settings, "AUTH_MODE", "google")
    yield
    http_client.transport = None


def _mock(scope: str):
    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3599, "scope": scope})
        return httpx.Response(200, json={"sub": "g", "email": "me@x.com", "email_verified": True, "name": "Me"})
    http_client.transport = httpx.MockTransport(handler)


async def _login(scope):
    _mock(scope)
    state = oauth.make_state(0, "google_login")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/auth/google/callback?code=c&state={state}")
        conns = (await c.get("/connections")).json()
    return r, conns


def test_login_consent_asks_for_the_connector_scopes():
    url = oauth.authorize_url.__wrapped__ if hasattr(oauth.authorize_url, "__wrapped__") else None
    scopes = oauth.PROVIDERS["google_login"].scopes
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes and SHEETS in scopes
    assert oauth.PROVIDERS["google_login"].extra_authorize["access_type"] == "offline"
    assert url is None


async def test_full_grant_connects_gmail_and_sheets(session, google):
    r, conns = await _login(f"openid email profile {GMAIL} {SHEETS}")
    assert r.headers["location"] == "http://localhost:3100/today?connected=gmail,sheets"
    assert sorted((c["provider"], c["status"], c["kind"]) for c in conns) == [
        ("gmail", "connected", "oauth"), ("sheets", "connected", "oauth")]


async def test_partial_grant_connects_only_what_was_ticked(session, google):
    r, conns = await _login(f"openid email profile {SHEETS}")
    assert r.headers["location"].endswith("?connected=sheets")
    assert [c["provider"] for c in conns] == ["sheets"]


async def test_identity_only_grant_connects_nothing(session, google):
    r, conns = await _login("openid email profile")
    assert r.headers["location"] == "http://localhost:3100/today" and conns == []


async def test_signing_in_again_replaces_the_old_google_connections(session, google):
    await _login(f"openid email profile {GMAIL} {SHEETS}")
    _, conns = await _login(f"openid email profile {GMAIL} {SHEETS}")
    assert sorted(c["provider"] for c in conns) == ["gmail", "sheets"]


async def test_the_stored_token_refreshes_through_google_for_sheets(session, google):
    from sqlalchemy import select

    from app.models import Connection
    from app.security.secrets import parse_secret
    from app.security.tokens import _exchange

    await _login(f"openid email profile {SHEETS}")
    conn = (await session.execute(select(Connection).where(Connection.provider == "sheets"))).scalars().one()
    assert conn.kind == "oauth"

    def handler(request):
        form = dict(p.split("=") for p in request.content.decode().split("&"))
        assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "rt"
        return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
    http_client.transport = httpx.MockTransport(handler)
    from app.security.secrets import dump_secret
    blob, ttl = await _exchange("sheets", dump_secret("at", "rt", None))
    assert parse_secret(blob)["access_token"] == "new" and ttl == 3600


# ------------------------------------------------------------------ sheets connector
def test_spreadsheet_ids_come_out_of_urls():
    assert spreadsheet_id_from("https://docs.google.com/spreadsheets/d/1AbC_d-9/edit#gid=0") == "1AbC_d-9"
    assert spreadsheet_id_from("1AbC_d-9") == "1AbC_d-9"


async def test_sheets_read_append_update_hit_the_real_endpoints(monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_STUBS", False)
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.url.params.get("valueInputOption")))
        assert request.headers["authorization"] == "Bearer tok"
        if request.method == "GET":
            return httpx.Response(200, json={"range": "Sheet1!A1:B2", "values": [["a", "b"], ["1", "2"]]})
        if request.method == "POST":
            return httpx.Response(200, json={"updates": {"updatedRows": 2, "updatedRange": "Sheet1!A3:B4"}})
        return httpx.Response(200, json={"updatedRows": 1, "updatedRange": "Sheet1!A1:B1"})

    http_client.transport = httpx.MockTransport(handler)
    try:
        c = SheetsConnector()
        read = await c.read_range(credential="tok", spreadsheet="https://docs.google.com/spreadsheets/d/SID/edit", range="Sheet1!A1:B2")
        app_ = await c.append_rows(credential="tok", spreadsheet="SID", range="Sheet1", rows=[["x", 1], ["y", 2]])
        upd = await c.update_range(credential="tok", spreadsheet="SID", range="Sheet1!A1:B1", rows=[["z", 3]])
    finally:
        http_client.transport = None
    assert read["rows"] == [["a", "b"], ["1", "2"]] and app_["appended"] == 2 and upd["updated"] == 1
    assert seen == [
        ("GET", "/v4/spreadsheets/SID/values/Sheet1!A1:B2", None),
        ("POST", "/v4/spreadsheets/SID/values/Sheet1:append", "USER_ENTERED"),
        ("PUT", "/v4/spreadsheets/SID/values/Sheet1!A1:B1", "USER_ENTERED"),
    ]
