"""One place to build outbound HTTP clients, so tests can swap the transport.

`transport` is None in production (real network). A test sets it to an
`httpx.MockTransport` and every connector and the OAuth client go through it.
"""

from __future__ import annotations

import httpx

from app.config import settings

transport: httpx.AsyncBaseTransport | None = None


def client(timeout: float | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout or settings.TOOL_CALL_TIMEOUT_SECONDS, transport=transport
    )
