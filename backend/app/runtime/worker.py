"""Picks jobs off the queue and runs them. The only process you scale."""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.db import async_session_factory
from app.runtime.bus import pop
from app.runtime.runs import perform_run

logger = logging.getLogger("worker")


async def handle(job: dict) -> None:
    async with async_session_factory() as session:
        run = await perform_run(
            session, job["run_id"], prompt_override=job.get("prompt_override")
        )
        logger.info("run %s finished · %s", run.id, run.status)


async def run_forever() -> None:
    logger.info("worker up · queue=%s", settings.JOB_QUEUE)
    while True:
        try:
            job = await pop(settings.JOB_QUEUE, timeout=5)
        except Exception:  # noqa: BLE001 - the loop outlives any queue hiccup
            logger.exception("queue read failed")
            await asyncio.sleep(1)
            continue
        if job is None:
            continue
        try:
            await handle(job)
        except Exception:  # noqa: BLE001 - one bad job must not kill the worker
            logger.exception("job failed: %s", job)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(name)s: %(message)s")
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
