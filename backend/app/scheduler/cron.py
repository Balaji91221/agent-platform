"""Turn "0 9 * * *" plus a timezone into the next due instant.

The timezone is the point: 9am must mean 9am where the user is, not where the
server happens to run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.errors import ValidationException
from app.models import Schedule, utcnow


def validate_cron(expression: str) -> None:
    if not croniter.is_valid(expression):
        raise ValidationException(f"'{expression}' is not a valid cron expression")


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationException(f"Unknown timezone '{name}'") from exc


def next_due(expression: str, tz_name: str, after: datetime | None = None) -> datetime:
    """Next firing time, computed in the user's zone and returned in UTC."""
    validate_cron(expression)
    tz = zone(tz_name)
    base = (after or utcnow()).astimezone(tz)
    nxt = croniter(expression, base).get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=tz)
    return nxt.astimezone(timezone.utc)


_DAY_NAMES = {"0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday",
              "4": "Thursday", "5": "Friday", "6": "Saturday", "7": "Sunday"}


def describe(expression: str) -> str:
    """The plain-words line the UI shows under the cron rule.

    Covers the shapes the builder and the form produce; anything else returns
    "" so the UI shows the rule once rather than echoing it twice.
    """
    parts = expression.split()
    if len(parts) != 5:
        return ""
    minute, hour, dom, month, dow = parts
    if dom != "*" or month != "*":
        return ""
    if minute.startswith("*/") and hour == "*" and dow == "*":
        return f"Every {minute[2:]} minutes"
    if minute.isdigit() and hour == "*" and dow == "*":
        return "Every hour, on the hour" if minute == "0" else f"Every hour at :{int(minute):02d}"
    if minute.isdigit() and hour.startswith("*/") and dow == "*":
        return f"Every {hour[2:]} hours"
    if not (minute.isdigit() and hour.isdigit()):
        return ""
    clock = f"{int(hour):02d}:{int(minute):02d}"
    if dow == "*":
        return f"Every day at {clock}"
    if dow == "1-5":
        return f"Weekdays at {clock}"
    if dow in _DAY_NAMES:
        return f"{_DAY_NAMES[dow]}s at {clock}"
    return ""


def preview(expression: str, tz_name: str, count: int = 3) -> list[str]:
    """The "next three runs" list on the create screen."""
    tz = zone(tz_name)
    validate_cron(expression)
    itr = croniter(expression, utcnow().astimezone(tz))
    return [itr.get_next(datetime).strftime("%a %d %b, %H:%M") for _ in range(count)]


async def advance_schedule(session: AsyncSession, agent_id: int) -> None:
    """After a run finishes, work out when the agent is next due."""
    result = await session.execute(select(Schedule).where(Schedule.agent_id == agent_id))
    schedule = result.scalar_one_or_none()
    if schedule is None or schedule.is_paused:
        return
    schedule.next_due_at = next_due(schedule.cron, schedule.timezone)
    await session.commit()
