"""OAuth2 authorization-code flow for the built-in providers.

`start` builds the provider's authorize URL with a signed `state`; `callback`
verifies the state, swaps the code for tokens, and stores them. `refresh`
renews an access token from its refresh token (called from tokens.usable_secret
just before use). An unconfigured provider refuses to start, with the env var
names in the message, instead of inventing a token.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

from app.config import settings
from app.connectors.http_client import client

STATE_TTL_SECONDS = 600


class OAuthNotConfigured(Exception):
    pass


class OAuthError(Exception):
    pass


@dataclass(frozen=True)
class Provider:
    authorize_url: str
    token_url: str
    scopes: list[str]
    client_id_var: str
    client_secret_var: str
    extra_authorize: dict = field(default_factory=dict)


PROVIDERS: dict[str, Provider] = {
    "gmail": Provider(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        client_id_var="GOOGLE_CLIENT_ID",
        client_secret_var="GOOGLE_CLIENT_SECRET",
        # offline + consent is what makes Google hand back a refresh token.
        extra_authorize={"access_type": "offline", "prompt": "consent"},
    ),
    # Website sign-in. Asks for the Google connectors in the same consent, so
    # one sign-in also connects Gmail and Sheets (see GOOGLE_CONNECTOR_SCOPES).
    "google_login": Provider(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=[
            "openid", "email", "profile",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/spreadsheets",
        ],
        client_id_var="GOOGLE_CLIENT_ID",
        client_secret_var="GOOGLE_CLIENT_SECRET",
        extra_authorize={"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
    ),
    "sheets": Provider(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        client_id_var="GOOGLE_CLIENT_ID",
        client_secret_var="GOOGLE_CLIENT_SECRET",
        extra_authorize={"access_type": "offline", "prompt": "consent"},
    ),
    "slack": Provider(
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=[
            "chat:write", "channels:read", "channels:history", "groups:read",
            "users:read", "users:read.email", "im:write",
        ],
        client_id_var="SLACK_CLIENT_ID",
        client_secret_var="SLACK_CLIENT_SECRET",
    ),
}


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    scopes: frozenset[str] = frozenset()


def _credentials(provider: str) -> tuple[Provider, str, str]:
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise OAuthNotConfigured(f"{provider} has no OAuth flow; paste a token instead")
    client_id = getattr(settings, spec.client_id_var, "")
    client_secret = getattr(settings, spec.client_secret_var, "")
    if not client_id or not client_secret:
        raise OAuthNotConfigured(
            f"Sign-in with {provider} needs {spec.client_id_var} and "
            f"{spec.client_secret_var} in backend/.env; paste a token instead"
        )
    return spec, client_id, client_secret


def is_configured(provider: str) -> bool:
    try:
        _credentials(provider)
    except OAuthNotConfigured:
        return False
    return True


def redirect_uri(provider: str) -> str:
    base = settings.OAUTH_REDIRECT_BASE.rstrip("/")
    if provider == "google_login":
        return f"{base}/auth/google/callback"
    if provider == "gmail" and settings.GOOGLE_REDIRECT_URI:
        return settings.GOOGLE_REDIRECT_URI
    return f"{base}/connections/oauth/{provider}/callback"


# --- state: user id + provider + expiry, HMAC-signed so the callback can trust it
def _state_key() -> bytes:
    return hashlib.sha256((settings.CREDENTIAL_KEY or "agent-platform-dev-only-key").encode()).digest()


def make_state(user_id: int, provider: str) -> str:
    payload = f"{user_id}.{provider}.{int(time.time()) + STATE_TTL_SECONDS}.{secrets.token_urlsafe(8)}"
    sig = hmac.new(_state_key(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def verify_state(state: str, provider: str) -> int:
    """The user id the state was issued for; raises on tamper, expiry, or mismatch."""
    try:
        payload, sig = state.rsplit(".", 1)
        user_id, state_provider, expires, _nonce = payload.split(".")
    except ValueError as exc:
        raise OAuthError("malformed state") from exc
    expected = hmac.new(_state_key(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        raise OAuthError("state signature does not match")
    if state_provider != provider:
        raise OAuthError("state was issued for a different provider")
    if int(expires) < time.time():
        raise OAuthError("sign-in took too long; start again")
    return int(user_id)


def authorize_url(provider: str, user_id: int) -> str:
    spec, client_id, _ = _credentials(provider)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": " ".join(spec.scopes),
        "state": make_state(user_id, provider),
        **spec.extra_authorize,
    }
    return f"{spec.authorize_url}?{urlencode(params)}"


async def _token_request(spec: Provider, form: dict) -> dict:
    async with client(timeout=20) as http:
        response = await http.post(
            spec.token_url, data=form, headers={"Accept": "application/json"}
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise OAuthError(f"token endpoint returned HTTP {response.status_code}") from exc
    # Google signals errors by status; Slack by ok=false with a 200.
    if response.status_code >= 400 or data.get("ok") is False or "error" in data:
        raise OAuthError(str(data.get("error_description") or data.get("error") or response.status_code))
    return data


def _tokens(data: dict) -> TokenSet:
    access = data.get("access_token") or data.get("authed_user", {}).get("access_token")
    if not access:
        raise OAuthError("token response carried no access_token")
    return TokenSet(
        access_token=access,
        refresh_token=data.get("refresh_token"),
        expires_in=int(data["expires_in"]) if data.get("expires_in") else None,
        scopes=frozenset(str(data.get("scope") or "").split()),
    )


async def exchange_code(provider: str, code: str) -> TokenSet:
    spec, client_id, client_secret = _credentials(provider)
    data = await _token_request(
        spec,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(provider),
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    return _tokens(data)


async def refresh(provider: str, refresh_token: str) -> TokenSet:
    spec, client_id, client_secret = _credentials(provider)
    data = await _token_request(
        spec,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    tokens = _tokens(data)
    # Most providers omit the refresh token on renewal; keep the one we have.
    return TokenSet(tokens.access_token, tokens.refresh_token or refresh_token, tokens.expires_in, tokens.scopes)


USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None
    picture: str | None


async def fetch_google_identity(access_token: str) -> GoogleIdentity:
    async with client(timeout=20) as http:
        response = await http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    try:
        data = response.json()
    except ValueError as exc:
        raise OAuthError(f"userinfo returned HTTP {response.status_code}") from exc
    if response.status_code >= 400 or not data.get("email"):
        raise OAuthError(str(data.get("error_description") or data.get("error") or "no email in profile"))
    if data.get("email_verified") is False:
        raise OAuthError("Google account email is not verified")
    return GoogleIdentity(
        sub=str(data.get("sub")), email=data["email"].lower(),
        name=data.get("name"), picture=data.get("picture"),
    )


# Which connector each Google scope unlocks. A connection is created at sign-in
# only for providers whose every scope was actually granted.
GOOGLE_CONNECTOR_SCOPES: dict[str, set[str]] = {
    "gmail": {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    },
    "sheets": {"https://www.googleapis.com/auth/spreadsheets"},
}


def granted_google_connectors(scopes: frozenset[str]) -> list[str]:
    return [p for p, needed in GOOGLE_CONNECTOR_SCOPES.items() if needed <= scopes]
