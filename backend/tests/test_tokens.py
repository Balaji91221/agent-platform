"""OAuth token refresh at the point of use (plan §12 risk mitigation)."""

from datetime import timedelta

import pytest

from app.models import Connection, Credential, Notification, utcnow
from app.security.crypto import encrypt
from app.security.tokens import is_expiring, mark_expired, usable_secret


async def _oauth_connection(session, user, expires_in: timedelta | None) -> Connection:
    cred = Credential(
        ciphertext=encrypt("access-token-abc"),
        expires_at=(utcnow() + expires_in) if expires_in is not None else None,
    )
    session.add(cred)
    await session.commit()
    await session.refresh(cred)

    conn = Connection(
        user_id=user.id, kind="oauth", provider="gmail", label="Gmail",
        status="connected", credential_id=cred.id, config_json={},
    )
    session.add(conn)
    await session.commit()
    await session.refresh(conn)
    return conn


def test_a_token_with_no_expiry_never_refreshes():
    assert is_expiring(Credential(ciphertext="x", expires_at=None)) is False


def test_a_token_expiring_inside_the_margin_is_due():
    soon = Credential(ciphertext="x", expires_at=utcnow() + timedelta(minutes=1))
    later = Credential(ciphertext="x", expires_at=utcnow() + timedelta(hours=2))
    assert is_expiring(soon) is True
    assert is_expiring(later) is False


async def test_a_healthy_token_is_returned_untouched(session, user):
    conn = await _oauth_connection(session, user, timedelta(hours=2))
    assert await usable_secret(session, conn) == "access-token-abc"
    assert conn.status == "connected"


async def test_a_failed_refresh_expires_the_connection_and_notifies(session, user):
    """No OAuth client is configured, so the refresh must fail loudly."""
    conn = await _oauth_connection(session, user, timedelta(seconds=30))

    assert await usable_secret(session, conn) is None
    await session.refresh(conn)
    assert conn.status == "expired"

    from app.notify.dispatcher import deliver
    from app.runtime.bus import pop
    from app.config import settings

    event = await pop(settings.NOTIFY_QUEUE, timeout=2)
    assert event is not None and event["kind"] == "expiry"
    await deliver(session, event)

    rows = (await session.execute(Notification.__table__.select())).fetchall()
    assert len(rows) == 1


async def test_expired_connection_surfaces_as_a_tool_error(session, user):
    """The run reports why, instead of sending a dead token to the provider."""
    from app.runtime import router

    conn = await _oauth_connection(session, user, timedelta(seconds=5))
    await mark_expired(session, conn)

    with pytest.raises(router.ConnectionExpired):
        await router._credential_for_provider(session, user.id, "gmail")


async def test_mark_expired_notifies_only_once(session, user):
    from app.config import settings
    from app.runtime.bus import pop

    conn = await _oauth_connection(session, user, None)
    await mark_expired(session, conn)
    await mark_expired(session, conn)  # second call must be a no-op

    assert await pop(settings.NOTIFY_QUEUE, timeout=1) is not None
    assert await pop(settings.NOTIFY_QUEUE, timeout=1) is None
