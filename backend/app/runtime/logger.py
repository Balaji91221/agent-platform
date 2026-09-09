"""Plan FR-6 / NFR-9 — write each step to run_logs and publish it for streaming."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RunLog, utcnow
from app.runtime.bus import publish, run_channel


class RunLogger:
    """Sequenced, persisted, and streamed — in that order, so a client that
    attaches mid-run can replay from the database and miss nothing."""

    def __init__(self, session: AsyncSession, run_id: int):
        self._session = session
        self._run_id = run_id
        self._seq = 0

    async def load_seq(self) -> None:
        result = await self._session.execute(
            select(func.max(RunLog.seq)).where(RunLog.run_id == self._run_id)
        )
        self._seq = result.scalar() or 0

    async def write(self, line: str, kind: str = "t") -> RunLog:
        self._seq += 1
        entry = RunLog(
            run_id=self._run_id, seq=self._seq, kind=kind, line=line, at=utcnow()
        )
        self._session.add(entry)
        await self._session.commit()
        await publish(
            run_channel(self._run_id),
            {
                "seq": entry.seq,
                "at": entry.at.isoformat(),
                "kind": entry.kind,
                "line": entry.line,
            },
        )
        return entry

    async def info(self, line: str) -> None:
        await self.write(line, "t")

    async def ok(self, line: str) -> None:
        await self.write(line, "g")

    async def warn(self, line: str) -> None:
        await self.write(line, "y")

    async def error(self, line: str) -> None:
        await self.write(line, "r")
