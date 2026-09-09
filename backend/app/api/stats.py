"""Dashboard figures (plan FR-20) — every number computed from the runs table."""

from collections import Counter
from datetime import timedelta
from statistics import median

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.dependencies.auth import get_current_user
from app.models import Agent, Run, User, as_utc, utcnow
from app.schemas.rest import StatsOut

router = APIRouter(prefix="/stats", tags=["Stats"])

WINDOWS = {"today": 1, "7d": 7, "30d": 30}


@router.get("", response_model=StatsOut)
async def dashboard(
    range: str = Query(default="today", pattern="^(today|7d|30d)$"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    now = utcnow()
    since = now - timedelta(days=WINDOWS[range])

    rows = (
        await session.execute(
            select(Run, Agent)
            .join(Agent, Run.agent_id == Agent.id)
            .where(Agent.user_id == user.id, Run.created_at >= since)
        )
    ).all()

    runs = [r for r, _ in rows]
    # Normalise once: SQLite returns naive datetimes, Postgres aware ones.
    created = {r.id: as_utc(r.created_at) for r in runs}
    finished = [r for r in runs if r.status in {"succeeded", "failed"}]
    succeeded = [r for r in finished if r.status == "succeeded"]
    retried = [r for r in succeeded if r.attempt > 1]

    day_start = now - timedelta(days=1)
    week_start = now - timedelta(days=7)

    durations = [r.duration_seconds for r in finished if r.duration_seconds is not None]

    # Runs per hour across the last 24 hours, oldest bucket first.
    per_hour = Counter(
        created[r.id].hour for r in runs if created[r.id] >= day_start
    )
    hours = [
        {"hour": (now - timedelta(hours=h)).hour, "runs": per_hour.get((now - timedelta(hours=h)).hour, 0)}
        for h in range_reversed(24)
    ]

    busiest = Counter()
    for run, agent in rows:
        busiest[agent.name] += 1

    agents_used = (
        await session.execute(
            select(func.count()).select_from(Agent).where(Agent.user_id == user.id)
        )
    ).scalar() or 0

    return StatsOut(
        agents_used=agents_used,
        agent_limit=settings.MAX_AGENTS_PER_USER,
        runs_today=sum(1 for r in runs if created[r.id] >= day_start),
        runs_total=len(runs),
        success_rate=round(100 * len(succeeded) / len(finished), 1) if finished else 0.0,
        median_duration_seconds=round(median(durations), 1) if durations else None,
        failures_this_week=sum(
            1 for r in finished if r.status == "failed" and created[r.id] >= week_start
        ),
        runs_per_hour=hours,
        outcomes={
            "succeeded": len(succeeded) - len(retried),
            "retried_then_passed": len(retried),
            "failed": len(finished) - len(succeeded),
        },
        busiest_agents=[
            {"name": name, "runs": count} for name, count in busiest.most_common(5)
        ],
    )


def range_reversed(n: int) -> list[int]:
    return list(reversed(list(range(n))))
