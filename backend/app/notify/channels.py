"""The three delivery channels. Each one takes a rendered message and sends it."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger("notify")


def build_email(to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body or subject)
    return msg


def _smtp_send(msg: EmailMessage) -> None:
    """Blocking; runs in a thread. STARTTLS on 587 by default, plain SSL on 465."""
    if settings.SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
    with server:
        if settings.SMTP_STARTTLS and settings.SMTP_PORT != 465:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


async def _connection(session: AsyncSession, user_id: int, provider: str):
    from app.models import Connection

    return (
        await session.execute(
            select(Connection).where(
                Connection.user_id == user_id,
                Connection.provider == provider,
                Connection.status == "connected",
            )
        )
    ).scalars().first()


async def send_email(
    to: str,
    subject: str,
    body: str,
    *,
    session: AsyncSession | None = None,
    user_id: int | None = None,
) -> bool:
    """`console` prints instead of sending, so delivery is verifiable offline.
    `gmail` sends through the user's own Gmail connection (no SMTP needed)."""
    if settings.EMAIL_SENDER == "console":
        logger.info("EMAIL -> %s | %s | %s", to, subject, body)
        return True
    if settings.EMAIL_SENDER == "gmail":
        from app.connectors.gmail import GmailConnector
        from app.security.tokens import usable_secret

        if session is None or user_id is None:
            return False
        connection = await _connection(session, user_id, "gmail")
        if connection is None:
            logger.info("email skipped: user %s has no Gmail connection", user_id)
            return False
        secret = await usable_secret(session, connection)
        if secret is None:
            return False
        try:
            await GmailConnector().send(credential=secret, to=to, subject=subject, body=body or subject)
            return True
        except Exception as exc:  # noqa: BLE001 - a mail failure is not a run failure
            logger.warning("gmail send to %s failed: %s", to, exc)
            return False
    if settings.EMAIL_SENDER == "smtp":
        if not settings.SMTP_HOST:
            logger.warning("EMAIL_SENDER=smtp but SMTP_HOST is empty")
            return False
        try:
            await asyncio.to_thread(_smtp_send, build_email(to, subject, body))
            return True
        except Exception as exc:  # noqa: BLE001 - a mail failure is not a run failure
            logger.warning("smtp to %s failed: %s", to, exc)
            return False
    logger.warning("EMAIL_SENDER=%s is not implemented", settings.EMAIL_SENDER)
    return False


async def send_slack_dm(session: AsyncSession, user_id: int, email: str, text: str) -> bool:
    """Goes through the user's own Slack connection (plan §8 step 12).

    A bot token cannot post to `@handle`; Slack wants the member id, found from
    the email (`users.lookupByEmail`, scope users:read.email). Posting to that
    id opens the DM (scope im:write).
    """
    from app.connectors.slack import SlackConnector, _call
    from app.security.tokens import usable_secret

    connection = await _connection(session, user_id, "slack")
    if connection is None:
        if settings.CONNECTOR_STUBS:
            logger.info("SLACK DM (stub) -> %s | %s", email, text)
            return True
        logger.info("slack_dm skipped: user %s has no Slack connection", user_id)
        return False
    secret = await usable_secret(session, connection)
    if secret is None:
        return False
    try:
        from app.security.secrets import access_token

        token = access_token(secret) or ""
        member = await _call(token, "users.lookupByEmail", params={"email": email})
        await SlackConnector().post_message(
            credential=secret, channel=member["user"]["id"], text=text
        )
    except Exception as exc:  # noqa: BLE001 - a DM failure is not a run failure
        logger.warning("slack dm to %s failed: %s", email, exc)
        return False
    logger.info("SLACK DM -> %s | %s", email, text)
    return True


async def send_webhook(url: str, payload: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
        return response.status_code < 400
    except Exception as exc:  # noqa: BLE001 - a bad webhook is not a run failure
        logger.warning("webhook %s failed: %s", url, exc)
        return False
