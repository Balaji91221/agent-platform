"""YouTube Data API v3 connector — video metadata and search, read-only.

The key comes from a pasted connection or, failing that, YOUTUBE_API_KEY in
.env (a workspace-level key is normal for a public read-only API).
"""

from __future__ import annotations

import re
from typing import Any

from app.config import settings
from app.connectors.base import Connector, ConnectionMissing, ConnectorError, ToolSpec, collect, tool
from app.connectors.http_client import client
from app.security.secrets import access_token

API = "https://www.googleapis.com/youtube/v3"
_VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def _key(credential: str | None) -> str | None:
    if settings.CONNECTOR_STUBS:
        return None
    key = access_token(credential) or settings.YOUTUBE_API_KEY
    if not key:
        raise ConnectionMissing(
            "YouTube is not connected — paste an API key on the Connections screen "
            "or set YOUTUBE_API_KEY"
        )
    return key


def video_id_from(text: str) -> str:
    match = _VIDEO_ID.search(text)
    return match.group(1) if match else text.strip()


async def _get(key: str, path: str, params: dict) -> dict:
    async with client() as http:
        response = await http.get(f"{API}/{path}", params={**params, "key": key})
    try:
        data = response.json()
    except ValueError as exc:
        raise ConnectorError(f"YouTube {response.status_code}: not JSON") from exc
    if response.status_code >= 400:
        message = (data.get("error") or {}).get("message", response.text[:200])
        raise ConnectorError(f"YouTube {response.status_code}: {message}")
    return data


def _shape(item: dict) -> dict:
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    ident = item.get("id")
    if isinstance(ident, dict):
        ident = ident.get("videoId")
    return {
        "id": ident,
        "title": snippet.get("title"),
        "channel": snippet.get("channelTitle"),
        "published_at": snippet.get("publishedAt"),
        "description": (snippet.get("description") or "")[:500],
        "views": int(stats["viewCount"]) if stats.get("viewCount") else None,
        "likes": int(stats["likeCount"]) if stats.get("likeCount") else None,
        "comments": int(stats["commentCount"]) if stats.get("commentCount") else None,
        "duration": item.get("contentDetails", {}).get("duration"),
    }


class YouTubeConnector(Connector):
    provider = "youtube"
    label = "YouTube"

    @tool(
        "youtube.video_info",
        "Title, channel, publish date, views, likes, comments and duration of a video.",
        schema={
            "type": "object",
            "properties": {"video": {"type": "string", "description": "Video id or URL"}},
            "required": ["video"],
            "additionalProperties": False,
        },
    )
    async def video_info(self, credential: str | None = None, **kw: Any) -> dict:
        key = _key(credential)
        vid = video_id_from(str(kw["video"]))
        if key is None:
            return {"id": vid, "title": "(stub)", "views": 0}
        data = await _get(key, "videos", {"part": "snippet,statistics,contentDetails", "id": vid})
        items = data.get("items", [])
        if not items:
            raise ConnectorError(f"YouTube: no video with id {vid}")
        return _shape(items[0])

    @tool(
        "youtube.search",
        "Search videos by text; returns id, title, channel and publish date.",
        schema={
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            "required": ["q"],
            "additionalProperties": False,
        },
    )
    async def search(self, credential: str | None = None, **kw: Any) -> dict:
        key = _key(credential)
        if key is None:
            return {"videos": []}
        data = await _get(
            key,
            "search",
            {"part": "snippet", "type": "video", "q": kw["q"], "maxResults": int(kw.get("max_results") or 10)},
        )
        return {"videos": [_shape(i) for i in data.get("items", [])]}

    def tools(self) -> list[ToolSpec]:
        return collect(self)
