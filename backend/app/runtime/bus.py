"""Redis for the job queue, the notification queue, and live log fan-out.

Falls back to an in-process queue when Redis is absent, so a single-process dev
run still works end to end. Only the multi-process setup needs a real Redis.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_redis: Any | None = None
_redis_checked = False

# In-process fallbacks.
_local_queues: dict[str, asyncio.Queue] = {}
_local_subscribers: dict[str, list[asyncio.Queue]] = {}


class QueueUnavailable(Exception):
    """Redis is configured but cannot be reached; nothing can be queued."""


def _forget() -> None:
    """Drop the cached client so the next call reconnects."""
    global _redis, _redis_checked
    _redis = None
    _redis_checked = False


async def redis_alive() -> bool:
    """A real ping, for /health — the cached client alone says nothing."""
    client = await get_redis()
    if client is None:
        return False
    try:
        await asyncio.wait_for(client.ping(), timeout=1.0)
        return True
    except Exception:  # noqa: BLE001 - down is down
        _forget()
        return False


async def get_redis() -> Any | None:
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    try:
        import redis.asyncio as aioredis

        # socket_timeout must stay None: BLPOP blocks on the socket for its
        # whole timeout, and any read deadline shorter than that kills the pop.
        client = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_timeout=None
        )
        await client.ping()
        _redis = client
        logger.info("Redis connected at %s", settings.REDIS_URL)
    except Exception as exc:  # noqa: BLE001 - reported by the caller
        if settings.QUEUE_LOCAL_FALLBACK:
            logger.warning("Redis unavailable (%s); using in-process queues", exc)
        else:
            logger.warning("Redis unavailable (%s)", exc)
            _redis_checked = False  # try again next time rather than staying blind
        _redis = None
    return _redis


def _local(name: str) -> asyncio.Queue:
    return _local_queues.setdefault(name, asyncio.Queue())


async def push(queue: str, payload: dict) -> None:
    """Queue a job. Raises QueueUnavailable instead of silently using a local
    queue the worker process would never read."""
    client = await get_redis()
    if client is not None:
        try:
            await client.rpush(queue, json.dumps(payload))
            return
        except Exception as exc:  # noqa: BLE001 - connection dropped since the ping
            _forget()
            if not settings.QUEUE_LOCAL_FALLBACK:
                raise QueueUnavailable(f"Redis at {settings.REDIS_URL} is unreachable") from exc
    elif not settings.QUEUE_LOCAL_FALLBACK:
        raise QueueUnavailable(f"Redis at {settings.REDIS_URL} is unreachable")
    await _local(queue).put(payload)


async def pop(queue: str, timeout: int = 5) -> dict | None:
    """Block for `timeout` seconds. None means nothing arrived — never an error."""
    client = await get_redis()
    if client is not None:
        try:
            item = await client.blpop(queue, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - an idle window must not kill a worker
            _forget()
            logger.debug("blpop returned nothing (%s)", exc)
            return None
        return json.loads(item[1]) if item else None
    try:
        return await asyncio.wait_for(_local(queue).get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def publish(channel: str, payload: dict) -> None:
    """Fan a log line out to whoever is streaming this run."""
    client = await get_redis()
    if client is not None:
        await client.publish(channel, json.dumps(payload))
        return
    for q in _local_subscribers.get(channel, []):
        q.put_nowait(payload)


class Subscription:
    """Async iterator over one channel, Redis-backed or in-process."""

    def __init__(self, channel: str):
        self.channel = channel
        self._pubsub: Any | None = None
        self._queue: asyncio.Queue | None = None

    async def __aenter__(self) -> "Subscription":
        client = await get_redis()
        if client is not None:
            self._pubsub = client.pubsub()
            await self._pubsub.subscribe(self.channel)
        else:
            self._queue = asyncio.Queue()
            _local_subscribers.setdefault(self.channel, []).append(self._queue)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._pubsub is not None:
            await self._pubsub.unsubscribe(self.channel)
            await self._pubsub.close()
        elif self._queue is not None:
            subs = _local_subscribers.get(self.channel, [])
            if self._queue in subs:
                subs.remove(self._queue)

    async def next(self, timeout: float = 1.0) -> dict | None:
        if self._pubsub is not None:
            msg = await self._pubsub.get_message(
                ignore_subscribe_messages=True, timeout=timeout
            )
            return json.loads(msg["data"]) if msg else None
        assert self._queue is not None
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None


def run_channel(run_id: int) -> str:
    return f"{settings.RUN_CHANNEL_PREFIX}{run_id}"
