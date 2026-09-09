"""Current-user resolution.

AUTH_MODE=google: the signed session cookie set by Sign in with Google is the
only accepted identity; anything else is 401 and the frontend goes to /login.
AUTH_MODE=demo (tests, offline dev): an `X-User-Id` header, else the seeded
demo user. Every query is ownership-scoped, so nothing else changes between the
two modes.
"""

from fastapi import Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import session_scope
from app.exceptions.errors import UnauthorizedException
from app.models import NotificationPref, User
from app.security import session as session_tokens

DEMO_EMAIL = "arun@company.com"


async def ensure_demo_user(session: AsyncSession) -> User:
    result = await session.execute(select(User).where(User.email == DEMO_EMAIL))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=DEMO_EMAIL)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    await ensure_prefs(session, user.id)
    return user


async def ensure_prefs(session: AsyncSession, user_id: int) -> None:
    prefs = await session.execute(
        select(NotificationPref).where(NotificationPref.user_id == user_id)
    )
    if prefs.scalar_one_or_none() is None:
        session.add(NotificationPref(user_id=user_id))
        await session.commit()


async def get_current_user(
    request: Request,
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
) -> User:
    """Resolved in its own short-lived session, released before the handler runs.

    Sharing the request session here meant every open SSE stream pinned a pool
    connection for its whole life. The returned User is detached; handlers use
    `user.id`.
    """
    async with session_scope() as session:
        cookie_user = session_tokens.verify(request.cookies.get(settings.SESSION_COOKIE))
        if cookie_user is not None:
            user = (await session.execute(select(User).where(User.id == cookie_user))).scalar_one_or_none()
            if user is not None:
                return user
        if settings.AUTH_MODE == "google":
            raise UnauthorizedException()
        if x_user_id is not None:
            user = (await session.execute(select(User).where(User.id == x_user_id))).scalar_one_or_none()
            if user is not None:
                return user
        return await ensure_demo_user(session)
