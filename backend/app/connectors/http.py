"""Generic HTTP connector — the Custom HTTP option in the UI.

The user supplies a base URL and their own auth header on the connection; this
calls it. Real network call, unlike the app-specific stubs.
"""

from typing import Any

from app.connectors.base import Connector, ToolSpec, collect, tool
from app.connectors.http_client import client
from app.security.secrets import access_token


class HttpConnector(Connector):
    provider = "http"
    label = "Custom HTTP"

    @tool(
        "http.get",
        "GET a REST endpoint using the connection's base URL and auth header.",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    async def get(
        self, credential: str | None = None, config: dict | None = None, **kw: Any
    ) -> dict:
        cfg = config or {}
        base = cfg.get("base_url", "")
        headers = {}
        if credential and cfg.get("auth_header"):
            headers[cfg["auth_header"]] = access_token(credential) or ""
        url = base.rstrip("/") + "/" + str(kw.get("path", "")).lstrip("/")
        async with client() as http:
            response = await http.get(url, headers=headers)
            return {"status": response.status_code, "body": response.text[:2000]}

    @tool(
        "http.post",
        "POST a JSON body to a path under the connection's base URL.",
        writes=True,
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "body": {"type": "object", "description": "JSON body to send"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    )
    async def post(
        self, credential: str | None = None, config: dict | None = None, **kw: Any
    ) -> dict:
        cfg = config or {}
        base = cfg.get("base_url", "")
        headers = {}
        if credential and cfg.get("auth_header"):
            headers[cfg["auth_header"]] = access_token(credential) or ""
        url = base.rstrip("/") + "/" + str(kw.get("path", "")).lstrip("/")
        async with client() as http:
            response = await http.post(url, headers=headers, json=kw.get("body") or {})
            return {"status": response.status_code, "body": response.text[:2000]}

    def tools(self) -> list[ToolSpec]:
        return collect(self)
