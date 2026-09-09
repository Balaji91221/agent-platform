"""Run history, one run, and the live SSE log stream."""

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory, get_session, session_scope
from app.dependencies.auth import get_current_user
from app.models import RunLog, User
from app.runtime.bus import Subscription, run_channel
from app.schemas.agent import RunLogOut, RunOut
from app.security.ownership import get_owned_run

router = APIRouter(prefix="/runs", tags=["Runs"])


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    run_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_owned_run(session, run_id, user.id)


@router.get("/{run_id}/logs", response_model=list[RunLogOut])
async def get_logs(
    run_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await get_owned_run(session, run_id, user.id)
    rows = (
        await session.execute(
            select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.seq)
        )
    ).scalars().all()
    return list(rows)


@router.get("/{run_id}/stream")
async def stream_logs(
    run_id: int,
    user: User = Depends(get_current_user),
):
    """Plan FR-6 / NFR-9.

    Replays the rows already written, then follows the live channel — so a
    browser that attaches halfway through a run still sees the whole log.

    No `Depends(get_session)` here on purpose: a dependency session would stay
    checked out for the whole stream (one pool slot per open tab) and be torn
    down mid-cancel when the browser closes it, which is what filled the log
    with CancelledError tracebacks.
    """
    async def _load() -> tuple[str, list[dict]]:
        async with session_scope() as lookup:
            run = await get_owned_run(lookup, run_id, user.id)
            rows = (
                await lookup.execute(
                    select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.seq)
                )
            ).scalars().all()
            return run.status, [
                {"seq": r.seq, "at": r.at.isoformat(), "kind": r.kind, "line": r.line}
                for r in rows
            ]

    # All database work happens here, before the stream starts, and shielded:
    # once the generator below is running, a browser closing the tab can only
    # ever cancel a Redis wait — never a query mid-flight.
    status_now, replay = await asyncio.shield(_load())
    terminal = {"succeeded", "failed"}

    async def events():
        seen = 0
        for row in replay:
            seen = row["seq"]
            yield _sse(row)

        if status_now in terminal:
            yield _sse({"event": "done", "status": status_now})
            return

        async with Subscription(run_channel(run_id)) as sub:
            idle = 0
            while idle < 300:  # ~5 minutes, matching the run cap
                message = await sub.next(timeout=1.0)
                if message is None:
                    idle += 1
                    yield ": keep-alive\n\n"
                    continue
                idle = 0
                if message.get("event") == "done":
                    yield _sse(message)
                    return
                if message.get("seq", 0) > seen:
                    seen = message["seq"]
                    yield _sse(message)
            yield _sse({"event": "timeout"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
