"""Feed, mark read, and delivery preferences."""

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.dependencies.auth import get_current_user
from app.exceptions.errors import NotFoundException
from app.models import Agent, Notification, NotificationPref, Run, User
from app.notify.dispatcher import get_prefs
from app.schemas.rest import NotificationOut, PrefsIn, PrefsOut

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _shape(row: Notification, agent_id: int | None, agent_name: str | None) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        kind=row.kind,
        title=row.title,
        body=row.body,
        run_id=row.run_id,
        agent_id=agent_id,
        agent_name=agent_name or "",
        is_read=row.is_read,
        at=row.at,
    )


@router.get("", response_model=list[NotificationOut])
async def feed(
    limit: int = 50,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Newest first, each row carrying the agent its run belonged to (if any)."""
    rows = (
        await session.execute(
            select(Notification, Agent.id, Agent.name)
            .outerjoin(Run, Run.id == Notification.run_id)
            .outerjoin(Agent, Agent.id == Run.agent_id)
            .where(Notification.user_id == user.id)
            .order_by(Notification.at.desc(), Notification.id.desc())
            .limit(limit)
        )
    ).all()
    return [_shape(row, agent_id, agent_name) for row, agent_id, agent_name in rows]


@router.post("/read-all")
async def mark_all_read(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await session.commit()
    return {"marked": result.rowcount}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """One row, so opening a notification clears it without touching the rest."""
    row = (
        await session.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundException("Notification", notification_id)
    row.is_read = True
    await session.commit()
    return {"marked": 1}


def _prefs_out(prefs: NotificationPref, user: User) -> PrefsOut:
    out = PrefsOut.model_validate(prefs)
    out.email_to = settings.NOTIFY_EMAIL or user.email
    return out


@router.get("/prefs", response_model=PrefsOut)
async def read_prefs(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    return _prefs_out(await get_prefs(session, user.id), user)


@router.put("/prefs", response_model=PrefsOut)
async def write_prefs(
    payload: PrefsIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    prefs = await get_prefs(session, user.id)
    # Only the fields the caller sent change. A partial body used to reset
    # every other toggle to its default, which turned Slack DMs off silently.
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(prefs, key, value)
    await session.commit()
    await session.refresh(prefs)
    return _prefs_out(prefs, user)
