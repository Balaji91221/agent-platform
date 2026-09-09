"""Sign in with Google for the website itself (identity only, no Gmail scopes)."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.dependencies.auth import DEMO_EMAIL, ensure_prefs, get_current_user
from app.models import utcnow
from app.exceptions.errors import ValidationException
from app.models import Connection, Credential, User
from app.security.crypto import encrypt
from app.security.secrets import dump_secret
from app.schemas.rest import MeOut
from app.security import oauth
from app.security import session as session_tokens

router = APIRouter(prefix="/auth", tags=["Auth"])
LOGIN = "google_login"


def _cookie(response: Response, token: str | None) -> None:
    if token is None:
        response.delete_cookie(settings.SESSION_COOKIE, path="/")
        return
    response.set_cookie(
        settings.SESSION_COOKIE,
        token,
        max_age=settings.SESSION_TTL_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.OAUTH_REDIRECT_BASE.startswith("https://"),
        path="/",
    )


@router.get("/google/start")
async def google_start():
    """Sends the browser straight to Google. 422 when no client is configured."""
    try:
        url = oauth.authorize_url(LOGIN, user_id=0)
    except oauth.OAuthNotConfigured as exc:
        raise ValidationException(str(exc)) from exc
    return RedirectResponse(url, status_code=303)


async def _upsert(session: AsyncSession, identity: oauth.GoogleIdentity) -> User:
    """Find by Google id, then by email; else claim the demo user or create."""
    user = (
        await session.execute(select(User).where(User.google_sub == identity.sub))
    ).scalar_one_or_none()
    if user is None:
        user = (
            await session.execute(select(User).where(User.email == identity.email))
        ).scalar_one_or_none()
    if user is None and settings.CLAIM_DEMO_USER:
        demo = (await session.execute(select(User).where(User.email == DEMO_EMAIL))).scalar_one_or_none()
        if demo is not None and demo.google_sub is None:
            user = demo
    if user is None:
        user = User(email=identity.email)
        session.add(user)
    user.email = identity.email
    user.google_sub = identity.sub
    user.name = identity.name
    user.picture = identity.picture
    await session.commit()
    await session.refresh(user)
    await ensure_prefs(session, user.id)
    return user


@router.get("/google/callback")
async def google_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    front = settings.FRONTEND_URL.rstrip("/")
    try:
        oauth.verify_state(state, LOGIN)
        if error or not code:
            raise oauth.OAuthError(error or "no code returned")
        tokens = await oauth.exchange_code(LOGIN, code)
        identity = await oauth.fetch_google_identity(tokens.access_token)
    except (oauth.OAuthError, oauth.OAuthNotConfigured) as exc:
        return RedirectResponse(f"{front}/login?error={quote(str(exc))}", status_code=303)

    user = await _upsert(session, identity)
    connected = await connect_google_providers(session, user.id, tokens)
    target = f"{front}/today" + (f"?connected={','.join(connected)}" if connected else "")
    response = RedirectResponse(target, status_code=303)
    _cookie(response, session_tokens.issue(user.id))
    return response


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request):
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _cookie(response, None)
    return response


async def connect_google_providers(
    session: AsyncSession, user_id: int, tokens: oauth.TokenSet
) -> list[str]:
    """One sign-in, every Google connector the user granted (Gmail, Sheets).

    Each provider gets its own credential row holding the same token blob, so
    refreshing or disconnecting one never touches the other. A provider the
    user unticked on the consent screen is left alone.
    """
    granted = oauth.granted_google_connectors(tokens.scopes)
    expires_at = utcnow() + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None
    blob = dump_secret(
        tokens.access_token, tokens.refresh_token,
        expires_at.isoformat(timespec="seconds") if expires_at else None,
    )
    for provider in granted:
        credential = Credential(ciphertext=encrypt(blob), expires_at=expires_at)
        session.add(credential)
        await session.flush()
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
                user_id=user_id, kind="oauth", provider=provider,
                label={"gmail": "Gmail", "sheets": "Google Sheets"}.get(provider, provider.title()),
                status="connected", credential_id=credential.id, config_json={},
            )
        )
    await session.commit()
    return granted
