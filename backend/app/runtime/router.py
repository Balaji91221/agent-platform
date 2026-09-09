"""Plan §8 step 8 — one tool name in, the right caller out.

The model sees one flat list. A built-in name goes to its connector; an
`mcp:{server_id}.{tool}` name goes to the MCP client. Both fetch their
credential from the encrypted store, and both are cancelled at 30 seconds.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors import registry
from app.connectors.base import ConnectionMissing  # noqa: F401 - re-exported for the executor
from app.exceptions.errors import ValidationException
from app.mcp import client as mcp_client
from app.mcp.cache import ensure_fresh
from app.models import AgentTool, Connection, Credential, McpServer
from app.security.crypto import decrypt
from app.security.tokens import usable_secret

MCP_PREFIX = "mcp:"


@dataclass
class ResolvedTool:
    name: str
    description: str
    schema: dict[str, Any]
    writes: bool


class ToolDenied(Exception):
    """Raised when a write tool is called without can_write (plan FR-15)."""


class ConnectionExpired(Exception):
    """The connection this tool needs can no longer be used."""


async def _credential_for_provider(
    session: AsyncSession, user_id: int, provider: str
) -> tuple[str | None, dict]:
    # Deliberately not filtered by status: an already-expired connection must
    # raise, not quietly look like "no credential" and let the tool run unauthed.
    result = await session.execute(
        select(Connection).where(
            Connection.user_id == user_id, Connection.provider == provider
        ).order_by(Connection.status.desc())
    )
    conn = result.scalars().first()
    if conn is None:
        if settings.CONNECTOR_STUBS:
            return None, {}
        raise ConnectionMissing(
            f"{provider} is not connected — connect it on the Connections screen"
        )
    if conn.status == "expired":
        raise ConnectionExpired(
            f"{provider} access expired — reconnect it on the Connections screen"
        )
    if conn.credential_id is None:
        return None, conn.config_json or {}

    # Decrypted here, in memory, immediately before the call — never earlier —
    # and refreshed first if it is about to expire.
    secret = await usable_secret(session, conn)
    if secret is None and conn.status == "expired":
        raise ConnectionExpired(
            f"{provider} access expired — reconnect it on the Connections screen"
        )
    return secret, (conn.config_json or {})


def _split_mcp(tool_name: str) -> tuple[int, str]:
    body = tool_name[len(MCP_PREFIX) :]
    server_id, _, remote = body.partition(".")
    return int(server_id), remote


async def build_tool_list(
    session: AsyncSession, agent_id: int, user_id: int
) -> tuple[list[ResolvedTool], dict[str, bool]]:
    """The flat list handed to the model, plus each tool's can_write flag."""
    rows = (
        await session.execute(select(AgentTool).where(AgentTool.agent_id == agent_id))
    ).scalars().all()

    resolved: list[ResolvedTool] = []
    can_write: dict[str, bool] = {}

    for row in rows:
        can_write[row.tool_name] = row.can_write

        if row.tool_name.startswith(MCP_PREFIX):
            server_id, remote = _split_mcp(row.tool_name)
            server = await session.get(McpServer, server_id)
            if server is None or server.user_id != user_id:
                continue
            # Plan NFR-7: the tool list is refreshed at most hourly, here, once per run.
            server = await ensure_fresh(session, server)
            if server.status != "ready":
                continue
            spec = next(
                (t for t in (server.tools_json or []) if t.get("name") == remote), None
            )
            if spec is None:
                continue
            resolved.append(
                ResolvedTool(
                    name=row.tool_name,
                    description=spec.get("description", remote),
                    schema=spec.get("inputSchema") or {"type": "object", "properties": {}},
                    writes=row.can_write,
                )
            )
            continue

        spec = registry.get_tool(row.tool_name)
        if spec is None:
            continue
        resolved.append(
            ResolvedTool(
                name=spec.name,
                description=spec.description,
                schema=spec.schema,
                writes=spec.writes,
            )
        )

    return resolved, can_write


async def call(
    session: AsyncSession,
    *,
    user_id: int,
    tool_name: str,
    arguments: dict[str, Any],
    can_write: dict[str, bool],
) -> Any:
    """Route one call. Enforces can_write, then the 30-second cancel (NFR-8)."""
    if tool_name.startswith(MCP_PREFIX):
        server_id, remote = _split_mcp(tool_name)
        server = await session.get(McpServer, server_id)
        if server is None or server.user_id != user_id:
            raise ValidationException(f"Unknown MCP server for tool {tool_name}")
        if not can_write.get(tool_name, False) and _looks_like_write(remote):
            raise ToolDenied(f"{tool_name} writes and can_write is not set")

        credential = None
        if server.credential_id is not None:
            cred = await session.get(Credential, server.credential_id)
            credential = decrypt(cred.ciphertext) if cred else None

        coro = mcp_client.call_tool(
            server.url, remote, arguments, server.auth_kind, credential
        )
    else:
        spec = registry.get_tool(tool_name)
        if spec is None:
            raise ValidationException(f"Unknown tool {tool_name}")
        if spec.writes and not can_write.get(tool_name, False):
            raise ToolDenied(f"{tool_name} writes and can_write is not set")

        provider = registry.provider_for(tool_name) or ""
        credential, config = await _credential_for_provider(session, user_id, provider)
        coro = spec.handler(credential=credential, config=config, **arguments)

    return await asyncio.wait_for(coro, timeout=settings.TOOL_CALL_TIMEOUT_SECONDS)


def _looks_like_write(remote_name: str) -> bool:
    lowered = remote_name.lower()
    return any(
        word in lowered
        for word in ("create", "send", "delete", "update", "post", "pay", "write", "remove")
    )
