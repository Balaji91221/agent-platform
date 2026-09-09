"""Signed session cookie for Sign in with Google.

`user_id.expires.nonce.signature`, HMAC-SHA256 under CREDENTIAL_KEY. Nothing is
stored server-side; logout clears the cookie and expiry ends it. Good enough for
a single-tenant deployment; swap for a sessions table if revocation is needed.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from app.config import settings


def _key() -> bytes:
    return hashlib.sha256(
        (settings.CREDENTIAL_KEY or "agent-platform-dev-only-key").encode() + b"|session"
    ).digest()


def issue(user_id: int, ttl_seconds: int | None = None) -> str:
    ttl = ttl_seconds if ttl_seconds is not None else settings.SESSION_TTL_DAYS * 86400
    payload = f"{user_id}.{int(time.time()) + ttl}.{secrets.token_urlsafe(9)}"
    sig = hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify(token: str | None) -> int | None:
    """The user id the token was issued for, or None if missing, forged, or expired."""
    if not token:
        return None
    try:
        payload, sig = token.rsplit(".", 1)
        user_id, expires, _nonce = payload.split(".")
    except ValueError:
        return None
    expected = hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if int(expires) < time.time():
        return None
    return int(user_id)
