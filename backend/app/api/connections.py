"""Connections: list, add api_key / custom_http, OAuth start + callback, delete."""

from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from app.connectors.registry import catalog, known_providers
from app.db import get_session
from app.dependencies.auth import get_current_user
from app.exceptions.errors import ValidationException
from app.models import Connection, Credential, User, utcnow
from app.schemas.rest import ConnectionCreate, ConnectionOut
from app.security import oauth
from app.security.crypto import encrypt
from app.security.secrets import dump_secret
from app.security.ownership import get_owned_connection, owned

router = APIRouter(prefix="/connections", tags=["Connections"])


@router.get("/tools")
async def list_tools(user: User = Depends(get_current_user)):
    """The built-in tool catalogue the create screen offers."""
    return catalog()


@router.get("", response_model=list[ConnectionOut])
async def list_connections(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    rows = (await session.execute(owned(Connection, user.id))).scalars().all()
    return list(rows)


@router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def add_connection(
    payload: ConnectionCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if payload.kind == "oauth":
        raise ValidationException(
            "Use GET /connections/oauth/{provider}/start for an OAuth connection"
        )
    if payload.provider not in known_providers():
        raise ValidationException(
            f"No connector for '{payload.provider}' yet; available: {', '.join(sorted(known_providers()))}"
        )
    if not payload.secret:
        raise ValidationException("A secret is required for this connection kind")
    if payload.kind == "custom_http" and not payload.base_url:
        raise ValidationException("custom_http needs a base_url")

    credential = Credential(ciphertext=encrypt(payload.secret))
    session.add(credential)
    await session.commit()
    await session.refresh(credential)

    connection = Connection(
        user_id=user.id,
        kind=payload.kind,
        provider=payload.provider,
        label=payload.label or payload.provider,
        status="connected",
        credential_id=credential.id,
        config_json={"base_url": payload.base_url, "auth_header": payload.auth_header},
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return connection


@router.get("/oauth/{provider}/start")
async def oauth_start(provider: str, user: User = Depends(get_current_user)):
    """Where to send the browser. 422 with the env var names when unconfigured."""
    try:
        url = oauth.authorize_url(provider, user.id)
    except oauth.OAuthNotConfigured as exc:
        raise ValidationException(str(exc)) from exc
    return {"provider": provider, "authorize_url": url}


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    state: str,
    code: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """The provider sends the browser here. Exchanges the code, stores the tokens
    encrypted, and bounces the browser back to the Connections screen.

    The user comes from the signed state, not a header: a browser redirect
    carries neither X-User-Id nor a session.
    """
    back = f"{settings.FRONTEND_URL.rstrip('/')}/connections"
    try:
        user_id = oauth.verify_state(state, provider)
        if error or not code:
            raise oauth.OAuthError(error or "no code returned")
        tokens = await oauth.exchange_code(provider, code)
    except (oauth.OAuthError, oauth.OAuthNotConfigured) as exc:
        return RedirectResponse(f"{back}?oauth_error={quote(str(exc))}", status_code=303)

    expires_at = (
        utcnow() + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None
    )
    credential = Credential(
        ciphertext=encrypt(
            dump_secret(
                tokens.access_token,
                tokens.refresh_token,
                expires_at.isoformat(timespec="seconds") if expires_at else None,
            )
        ),
        expires_at=expires_at,
    )
    session.add(credential)
    await session.commit()
    await session.refresh(credential)

    # Reconnecting replaces the old row so an expired one stops blocking teammates.
    existing = (
        await session.execute(
            select(Connection).where(Connection.user_id == user_id, Connection.provider == provider)
        )
    ).scalars().all()
    for old in existing:
        if old.credential_id is not None:
            old_cred = await session.get(Credential, old.credential_id)
            if old_cred is not None:
                await session.delete(old_cred)
        await session.delete(old)

    session.add(
        Connection(
            user_id=user_id,
            kind="oauth",
            provider=provider,
            label=provider.title(),
            status="connected",
            credential_id=credential.id,
            config_json={},
        )
    )
    await session.commit()
    return RedirectResponse(f"{back}?connected={provider}", status_code=303)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    connection_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    connection = await get_owned_connection(session, connection_id, user.id)
    await session.delete(connection)
    await session.commit()
