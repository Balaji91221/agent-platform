"""Plan NFR-7 — the tool list is cached and refreshed at most hourly, never per run."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp import client as mcp_client
from app.models import Credential, McpServer, as_utc, utcnow
from app.security.crypto import decrypt

REFRESH_AFTER = timedelta(hours=1)


async def _credential(session: AsyncSession, server: McpServer) -> str | None:
    if server.credential_id is None:
        return None
    cred = await session.get(Credential, server.credential_id)
    return decrypt(cred.ciphertext) if cred else None


async def refresh(session: AsyncSession, server: McpServer) -> McpServer:
    """Handshake now and store the outcome on the row."""
    credential = await _credential(session, server)
    result = await mcp_client.handshake(server.url, server.auth_kind, credential)

    server.last_handshake_at = utcnow()
    if result.ok:
        server.status = "ready"
        server.tools_json = result.tools
        server.error = None
        if result.server_name and not server.name:
            server.name = result.server_name
    else:
        server.status = "handshake_failed"
        server.error = result.error

    await session.commit()
    await session.refresh(server)
    return server


def is_stale(server: McpServer) -> bool:
    last = as_utc(server.last_handshake_at)
    if last is None:
        return True
    return utcnow() - last > REFRESH_AFTER


async def ensure_fresh(session: AsyncSession, server: McpServer) -> McpServer:
    if is_stale(server):
        return await refresh(session, server)
    return server


def qualified_names(server: McpServer) -> list[str]:
    """`mcp:{server_id}.{tool}` — the prefix that stops MCP tools colliding with
    built-ins (plan §12)."""
    return [f"mcp:{server.id}.{t.get('name')}" for t in (server.tools_json or [])]
