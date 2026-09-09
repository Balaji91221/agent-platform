"""Google Sheets connector — read, append and update ranges with the user's token."""

from __future__ import annotations

import re
from typing import Any

from app.connectors.base import Connector, ConnectorError, ToolSpec, collect, require_token, tool
from app.connectors.http_client import client

API = "https://sheets.googleapis.com/v4/spreadsheets"
_SHEET_ID = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


def spreadsheet_id_from(text: str) -> str:
    match = _SHEET_ID.search(text)
    return match.group(1) if match else text.strip()


def _check(response) -> dict:
    try:
        data = response.json()
    except ValueError as exc:
        raise ConnectorError(f"Sheets {response.status_code}: not JSON") from exc
    if response.status_code >= 400:
        raise ConnectorError(f"Sheets {response.status_code}: {(data.get('error') or {}).get('message', '')}")
    return data


async def _call(token: str, method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
    async with client() as http:
        response = await http.request(
            method, f"{API}/{path}", params=params, json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    return _check(response)


class SheetsConnector(Connector):
    provider = "sheets"
    label = "Google Sheets"

    @tool(
        "sheets.read_range",
        "Read cells from a sheet, e.g. range 'Sheet1!A1:D20'. Returns rows of values.",
        schema={
            "type": "object",
            "properties": {
                "spreadsheet": {"type": "string", "description": "Spreadsheet id or URL"},
                "range": {"type": "string"},
            },
            "required": ["spreadsheet", "range"],
            "additionalProperties": False,
        },
    )
    async def read_range(self, credential: str | None = None, **kw: Any) -> dict:
        token = require_token(credential, self.label)
        if token is None:
            return {"range": kw.get("range"), "rows": [["stub"]]}
        sid = spreadsheet_id_from(str(kw["spreadsheet"]))
        data = await _call(token, "GET", f"{sid}/values/{kw['range']}")
        return {"range": data.get("range"), "rows": data.get("values", [])}

    @tool(
        "sheets.append_rows",
        "Append rows after the last row of a range/sheet.",
        writes=True,
        schema={
            "type": "object",
            "properties": {
                "spreadsheet": {"type": "string"},
                "range": {"type": "string", "description": "Sheet or range to append to, e.g. 'Sheet1'"},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": ["string", "number", "boolean", "null"]}}},
            },
            "required": ["spreadsheet", "range", "rows"],
            "additionalProperties": False,
        },
    )
    async def append_rows(self, credential: str | None = None, **kw: Any) -> dict:
        token = require_token(credential, self.label)
        if token is None:
            return {"appended": len(kw.get("rows") or [])}
        sid = spreadsheet_id_from(str(kw["spreadsheet"]))
        data = await _call(
            token, "POST", f"{sid}/values/{kw['range']}:append",
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            body={"values": kw["rows"]},
        )
        updates = data.get("updates", {})
        return {"appended": updates.get("updatedRows", len(kw["rows"])), "range": updates.get("updatedRange")}

    @tool(
        "sheets.update_range",
        "Overwrite a range with rows of values.",
        writes=True,
        schema={
            "type": "object",
            "properties": {
                "spreadsheet": {"type": "string"},
                "range": {"type": "string"},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": ["string", "number", "boolean", "null"]}}},
            },
            "required": ["spreadsheet", "range", "rows"],
            "additionalProperties": False,
        },
    )
    async def update_range(self, credential: str | None = None, **kw: Any) -> dict:
        token = require_token(credential, self.label)
        if token is None:
            return {"updated": len(kw.get("rows") or [])}
        sid = spreadsheet_id_from(str(kw["spreadsheet"]))
        data = await _call(
            token, "PUT", f"{sid}/values/{kw['range']}",
            params={"valueInputOption": "USER_ENTERED"}, body={"values": kw["rows"]},
        )
        return {"updated": data.get("updatedRows", len(kw["rows"])), "range": data.get("updatedRange")}

    def tools(self) -> list[ToolSpec]:
        return collect(self)
