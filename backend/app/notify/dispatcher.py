"""Its own process and its own queue, so a slow mail provider never delays a run.

Reads the queue, checks quiet hours, and delivers on whichever channels are on.
Failures always pass quiet hours; nothing else does (plan FR-18).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import time as dtime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session_factory
from app.models import Agent, Notification, NotificationPref, Run, User, utcnow
from app.notify import channels
from app.runtime.bus import pop, push

logger = logging.getLogger("notifier")


def _parse_hhmm(value: str | None) -> dtime | None:
    if not value:
        return None
    try:
        hour, minute = value.split(":")
        return dtime(int(hour), int(minute))
    except (ValueError, AttributeError):
        return None


def in_quiet_hours(prefs: NotificationPref, now: dtime) -> bool:
    """True inside the window. Handles a window that wraps past midnight."""
    start = _parse_hhmm(prefs.quiet_from)
    end = _parse_hhmm(prefs.quiet_to)
    if start is None or end is None:
        return False
    if start <= end:
        return start <= now < end
    return now >= start or now < end


async def get_prefs(session: AsyncSession, user_id: int) -> NotificationPref:
    result = await session.execute(
        select(NotificationPref).where(NotificationPref.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = NotificationPref(user_id=user_id)
        session.add(prefs)
        await session.commit()
        await session.refresh(prefs)
    # A clock value stored before validation existed is treated as "not set",
    # and repaired in place, rather than breaking every read of this row.
    repaired = False
    for field in ("quiet_from", "quiet_to"):
        if _parse_hhmm(getattr(prefs, field)) is None and getattr(prefs, field):
            setattr(prefs, field, None)
            repaired = True
    if repaired:
        await session.commit()
    return prefs


async def queue_run_outcome(session: AsyncSession, agent: Agent, run: Run) -> None:
    """Called by the worker the moment a run's status is written."""
    prefs = await get_prefs(session, agent.user_id)
    if run.status == "failed":
        kind = "failure"
        title = f"{agent.name} failed"
        body = run.error or "The run failed after all retries."
    else:
        if not prefs.notify_on_success:
            return
        kind = "success"
        title = f"{agent.name} ran"
        body = run.output or "Completed."

    await push(
        settings.NOTIFY_QUEUE,
        {
            "user_id": agent.user_id,
            "kind": kind,
            "title": title,
            "body": body,
            "run_id": run.id,
        },
    )


async def queue_connection_expiry(user_id: int, provider: str) -> None:
    await push(
        settings.NOTIFY_QUEUE,
        {
            "user_id": user_id,
            "kind": "expiry",
            "title": f"{provider} access expired",
            "body": "Reconnect it before the next run breaks.",
            "run_id": None,
        },
    )


async def deliver(session: AsyncSession, event: dict) -> dict:
    """Write the feed row, then send on the allowed channels."""
    prefs = await get_prefs(session, event["user_id"])
    is_failure = event["kind"] == "failure"
    quiet = in_quiet_hours(prefs, utcnow().time())

    notification = Notification(
        user_id=event["user_id"],
        kind=event["kind"],
        title=event["title"],
        body=event.get("body", ""),
        run_id=event.get("run_id"),
    )
    session.add(notification)
    await session.commit()

    # Quiet hours hold everything except a real failure.
    if quiet and not is_failure:
        logger.info("held by quiet hours: %s", event["title"])
        return {"delivered": [], "held": True}

    user = await session.get(User, event["user_id"])
    delivered: list[str] = []

    # NOTIFY_EMAIL redirects everything to one inbox (dev / single-user setups).
    address = settings.NOTIFY_EMAIL or (user.email if user else "")
    if prefs.email_on and user is not None:
        if await channels.send_email(
            address, event["title"], event.get("body", ""), session=session, user_id=user.id
        ):
            delivered.append("email")
    if prefs.slack_dm_on and user is not None:
        if await channels.send_slack_dm(session, user.id, address, event["title"]):
            delivered.append("slack_dm")
    if prefs.webhook_on and prefs.webhook_url:
        if await channels.send_webhook(prefs.webhook_url, event):
            delivered.append("webhook")

    return {"delivered": delivered, "held": False}


async def run_forever() -> None:
    logger.info("notifier up · queue=%s", settings.NOTIFY_QUEUE)
    while True:
        try:
            event = await pop(settings.NOTIFY_QUEUE, timeout=5)
        except Exception:  # noqa: BLE001 - the loop outlives any queue hiccup
            logger.exception("queue read failed")
            await asyncio.sleep(1)
            continue
        if event is None:
            continue
        try:
            async with async_session_factory() as session:
                await deliver(session, event)
        except Exception:  # noqa: BLE001 - never let one event stop the notifier
            await requeue(event)


MAX_DELIVERY_ATTEMPTS = 5
REQUEUE_DELAY_SECONDS = 2.0


async def requeue(event: dict) -> bool:
    """Put a failed event back on the queue instead of dropping it.

    A database outage used to swallow every notification that arrived during
    it. Up to MAX_DELIVERY_ATTEMPTS tries, a short pause between them; after
    that it is logged and let go, so a poison event cannot loop forever.
    """
    attempts = int(event.get("_attempts", 0)) + 1
    if attempts >= MAX_DELIVERY_ATTEMPTS:
        logger.exception("delivery failed %s times, dropping: %s", attempts, event)
        return False
    logger.warning("delivery failed (attempt %s), re-queueing: %s", attempts, event.get("title"))
    await asyncio.sleep(REQUEUE_DELAY_SECONDS)
    try:
        await push(settings.NOTIFY_QUEUE, {**event, "_attempts": attempts})
    except Exception:  # noqa: BLE001 - the queue itself is down; nothing more to do
        logger.exception("could not re-queue, dropping: %s", event)
        return False
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(name)s: %(message)s")
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
