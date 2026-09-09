"""Gmail connector — the Gmail REST API with the user's OAuth token.

Every tool raises `ConnectionMissing` when Gmail has not been connected. Canned
answers exist only behind CONNECTOR_STUBS (tests).
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from app.connectors.base import Connector, ConnectorError, ToolSpec, collect, require_token, tool
from app.connectors.http_client import client

API = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_LIST = 25


async def _get(token: str, path: str, params: dict | None = None) -> dict:
    async with client() as http:
        response = await http.get(
            f"{API}/{path}", params=params, headers={"Authorization": f"Bearer {token}"}
        )
    return _check(response)


async def _post(token: str, path: str, body: dict) -> dict:
    async with client() as http:
        response = await http.post(
            f"{API}/{path}", json=body, headers={"Authorization": f"Bearer {token}"}
        )
    return _check(response)


def _check(response) -> dict:
    if response.status_code >= 400:
        try:
            message = response.json()["error"]["message"]
        except Exception:  # noqa: BLE001 - not JSON; show the body
            message = response.text[:200]
        raise ConnectorError(f"Gmail {response.status_code}: {message}")
    return response.json() if response.content else {}


def _header(message: dict, name: str) -> str:
    for h in message.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _body_text(payload: dict) -> str:
    """The first text/plain part, walking nested multiparts."""
    if payload.get("mimeType", "").startswith("text/plain"):
        data = payload.get("body", {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        found = _body_text(part)
        if found:
            return found
    return ""


class GmailConnector(Connector):
    provider = "gmail"
    label = "Gmail"

    @tool(
        "gmail.list_unread",
        "Returns sender, subject, and received time of unread mail. No message bodies.",
        schema={
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "Only mail after this date, YYYY/MM/DD"},
            },
            "additionalProperties": False,
        },
    )
    async def list_unread(self, credential: str | None = None, **kw: Any) -> dict:
        token = require_token(credential, self.label)
        if token is None:
            return {"count": 17, "senders": 9, "since": kw.get("since"), "messages": []}

        query = "is:unread" + (f" after:{kw['since']}" if kw.get("since") else "")
        listing = await _get(token, "messages", {"q": query, "maxResults": MAX_LIST})
        messages = []
        for ref in listing.get("messages", []):
            meta = await _get(
                token,
                f"messages/{ref['id']}",
                {"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
            messages.append(
                {
                    "id": ref["id"],
                    "from": _header(meta, "From"),
                    "subject": _header(meta, "Subject"),
                    "date": _header(meta, "Date"),
                }
            )
        senders = {m["from"] for m in messages}
        return {
            "count": listing.get("resultSizeEstimate", len(messages)),
            "senders": len(senders),
            "messages": messages,
        }

    @tool(
        "gmail.read_message",
        "Opens one message by id when the subject is not enough.",
        schema={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    )
    async def read_message(self, credential: str | None = None, **kw: Any) -> dict:
        token = require_token(credential, self.label)
        if token is None:
            return {"id": kw.get("id"), "body": "(message body)"}
        full = await _get(token, f"messages/{kw['id']}", {"format": "full"})
        return {
            "id": kw["id"],
            "from": _header(full, "From"),
            "subject": _header(full, "Subject"),
            "date": _header(full, "Date"),
            "snippet": full.get("snippet", ""),
            "body": _body_text(full.get("payload", {}))[:4000],
        }

    @tool(
        "gmail.send",
        "Sends mail as you.",
        writes=True,
        schema={
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
            "additionalProperties": False,
        },
    )
    async def send(self, credential: str | None = None, **kw: Any) -> dict:
        token = require_token(credential, self.label)
        if token is None:
            return {"sent": True, "to": kw.get("to")}
        raw = build_raw_email(kw["to"], kw["subject"], kw["body"])
        sent = await _post(token, "messages/send", {"raw": raw})
        return {"sent": True, "to": kw["to"], "id": sent.get("id")}

    def tools(self) -> list[ToolSpec]:
        return collect(self)


def build_raw_email(to: str, subject: str, body: str) -> str:
    """RFC 2822 message, base64url-encoded the way messages.send wants it."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
