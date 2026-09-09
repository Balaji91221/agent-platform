"""Slack connector — the Slack Web API with the workspace's bot token."""

from __future__ import annotations

from typing import Any

from app.connectors.base import Connector, ConnectorError, ToolSpec, collect, require_token, tool
from app.connectors.http_client import client

API = "https://slack.com/api"


async def _call(token: str, method: str, *, params: dict | None = None, body: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    async with client() as http:
        if body is not None:
            response = await http.post(f"{API}/{method}", json=body, headers=headers)
        else:
            response = await http.get(f"{API}/{method}", params=params, headers=headers)
    try:
        data = response.json()
    except ValueError as exc:
        raise ConnectorError(f"Slack {method}: HTTP {response.status_code}") from exc
    if not data.get("ok"):
        raise ConnectorError(f"Slack {method}: {data.get('error', 'unknown_error')}")
    return data


class SlackConnector(Connector):
    provider = "slack"
    label = "Slack"

    @tool(
        "slack.post_message",
        "Posts to a channel. Accepts a channel id or a #name.",
        writes=True,
        schema={
            "type": "object",
            "properties": {"channel": {"type": "string"}, "text": {"type": "string"}},
            "required": ["channel", "text"],
            "additionalProperties": False,
        },
    )
    async def post_message(self, credential: str | None = None, **kw: Any) -> dict:
        token = require_token(credential, self.label)
        if token is None:
            return {"ok": True, "channel": kw.get("channel", "#daily"), "ts": "1757312441.882"}
        data = await _call(
            token, "chat.postMessage", body={"channel": kw["channel"], "text": kw["text"]}
        )
        return {"ok": True, "channel": data.get("channel"), "ts": data.get("ts")}

    @tool("slack.list_channels", "Lists channels the bot can see, with their ids.")
    async def list_channels(self, credential: str | None = None, **kw: Any) -> dict:
        token = require_token(credential, self.label)
        if token is None:
            return {"channels": [{"id": "C1", "name": "daily"}, {"id": "C2", "name": "general"}]}
        data = await _call(
            token,
            "conversations.list",
            params={"types": "public_channel,private_channel", "limit": 200, "exclude_archived": "true"},
        )
        return {
            "channels": [{"id": c["id"], "name": c.get("name", "")} for c in data.get("channels", [])]
        }

    @tool(
        "slack.read_channel",
        "Reads recent history from a channel (id or #name).",
        schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["channel"],
            "additionalProperties": False,
        },
    )
    async def read_channel(self, credential: str | None = None, **kw: Any) -> dict:
        token = require_token(credential, self.label)
        if token is None:
            return {"messages": []}
        channel = await self._resolve(token, kw["channel"])
        data = await _call(
            token,
            "conversations.history",
            params={"channel": channel, "limit": int(kw.get("limit") or 20)},
        )
        return {
            "channel": channel,
            "messages": [
                {"user": m.get("user", ""), "text": m.get("text", ""), "ts": m.get("ts", "")}
                for m in data.get("messages", [])
            ],
        }

    async def _resolve(self, token: str, channel: str) -> str:
        """`#name` -> channel id; an id passes straight through."""
        if not channel.startswith("#"):
            return channel
        wanted = channel[1:].lower()
        listing = await _call(
            token,
            "conversations.list",
            params={"types": "public_channel,private_channel", "limit": 200},
        )
        for c in listing.get("channels", []):
            if c.get("name", "").lower() == wanted:
                return c["id"]
        raise ConnectorError(f"Slack: no channel named {channel}")

    def tools(self) -> list[ToolSpec]:
        return collect(self)
