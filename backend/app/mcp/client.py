"""MCP client — handshake, list tools, call a tool.

Speaks JSON-RPC over streamable HTTP; an SSE reply body is parsed too, which is
the second transport the UI offers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.exceptions.errors import UpstreamException

PROTOCOL_VERSION = "2025-06-18"


@dataclass
class HandshakeResult:
    ok: bool
    tools: list[dict[str, Any]]
    error: str | None = None
    server_name: str = ""


def auth_headers(auth_kind: str, credential: str | None) -> dict[str, str]:
    """Plan: attach bearer / OAuth / nothing."""
    if auth_kind in {"bearer", "oauth"} and credential:
        return {"Authorization": f"Bearer {credential}"}
    return {}


def _parse(response: httpx.Response) -> dict[str, Any]:
    """A streamable-HTTP server answers JSON; an SSE server answers text/event-stream."""
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise UpstreamException("SSE response carried no data frame")
    return response.json()


async def _rpc(
    url: str, method: str, params: dict, headers: dict[str, str], timeout: float
) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                **headers,
            },
        )
        response.raise_for_status()
        body = _parse(response)
    if "error" in body:
        raise UpstreamException(str(body["error"].get("message", body["error"])))
    return body.get("result", {})


async def handshake(
    url: str, auth_kind: str = "none", credential: str | None = None
) -> HandshakeResult:
    """Plan FR-10 — initialize, then read the tool list. Never raises."""
    headers = auth_headers(auth_kind, credential)
    timeout = float(settings.TOOL_CALL_TIMEOUT_SECONDS)
    try:
        init = await _rpc(
            url,
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agent-platform", "version": settings.APP_VERSION},
            },
            headers,
            timeout,
        )
        listed = await _rpc(url, "tools/list", {}, headers, timeout)
        tools = listed.get("tools", [])
        name = (init.get("serverInfo") or {}).get("name", "")
        return HandshakeResult(ok=True, tools=tools, server_name=name)
    except Exception as exc:  # noqa: BLE001 - the status field is the report
        return HandshakeResult(ok=False, tools=[], error=f"{type(exc).__name__}: {exc}")


async def call_tool(
    url: str,
    tool_name: str,
    arguments: dict[str, Any],
    auth_kind: str = "none",
    credential: str | None = None,
) -> Any:
    result = await _rpc(
        url,
        "tools/call",
        {"name": tool_name, "arguments": arguments},
        auth_headers(auth_kind, credential),
        float(settings.TOOL_CALL_TIMEOUT_SECONDS),
    )
    return result.get("content", result)
