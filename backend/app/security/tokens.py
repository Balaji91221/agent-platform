"""Plan §12 — refresh an expiring OAuth token just before use, never on a timer.

A timer wastes calls and still races the run that needs the token. Refreshing at
the point of use means the token is valid exactly when it matters. If the refresh
fails, the connection is marked `expired`, the user is notified once, and the
team thread can say which teammate is blocked instead of failing silently.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Connection, Credential, as_utc, utcnow
from app.security.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)

# Refresh a little before the token actually dies, so a slow run does not
# start with a token that expires halfway through.
REFRESH_MARGIN = timedelta(minutes=5)


class RefreshFailed(Exception):
    """The token could not be renewed; the connection is no longer usable."""


def is_expiring(credential: Credential | None) -> bool:
    if credential is None:
        return False
    expires = as_utc(credential.expires_at)
    if expires is None:
        return False  # a token with no expiry never needs refreshing
    return utcnow() + REFRESH_MARGIN >= expires


async def _exchange(provider: str, secret: str) -> tuple[str, int]:
    """Swap the stored refresh token for a new access token.

    Returns the new secret blob to store and its lifetime in seconds. Raises
    `RefreshFailed` when the provider has no OAuth client configured, the stored
    secret carries no refresh token, or the provider rejects it.
    """
    from app.security import oauth
    from app.security.secrets import dump_secret, parse_secret

    parsed = parse_secret(secret)
    refresh_token = parsed.get("refresh_token")
    if not refresh_token:
        raise RefreshFailed(f"{provider} connection has no refresh token; reconnect it")
    try:
        tokens = await oauth.refresh(provider, refresh_token)
    except oauth.OAuthNotConfigured as exc:
        raise RefreshFailed(str(exc)) from exc
    except oauth.OAuthError as exc:
        raise RefreshFailed(f"{provider} refused the refresh: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - network failure is a failed refresh
        raise RefreshFailed(f"{provider} refresh failed: {type(exc).__name__}") from exc

    ttl = tokens.expires_in or 3600
    expires_at = (utcnow() + timedelta(seconds=ttl)).isoformat(timespec="seconds")
    return dump_secret(tokens.access_token, tokens.refresh_token, expires_at), ttl


async def mark_expired(session: AsyncSession, connection: Connection) -> None:
    """Flip the connection and tell the user once."""
    if connection.status == "expired":
        return
    connection.status = "expired"
    await session.commit()

    from app.notify.dispatcher import queue_connection_expiry

    await queue_connection_expiry(connection.user_id, connection.provider)
    logger.warning(
        "connection %s (%s) marked expired", connection.id, connection.provider
    )


async def usable_secret(
    session: AsyncSession, connection: Connection
) -> str | None:
    """The decrypted secret for this connection, refreshed if it is about to die.

    Returns None once the connection is expired, so the caller fails with a clear
    reason rather than sending a dead token to the provider.
    """
    if connection.credential_id is None:
        return None

    credential = await session.get(Credential, connection.credential_id)
    if credential is None:
        return None

    if connection.kind != "oauth" or not is_expiring(credential):
        return decrypt(credential.ciphertext)

    try:
        new_token, ttl_seconds = await _exchange(
            connection.provider, decrypt(credential.ciphertext)
        )
    except RefreshFailed as exc:
        logger.warning("refresh failed for connection %s: %s", connection.id, exc)
        await mark_expired(session, connection)
        return None

    credential.ciphertext = encrypt(new_token)
    credential.expires_at = utcnow() + timedelta(seconds=ttl_seconds)
    await session.commit()
    return new_token
