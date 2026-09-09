"""Every built-in connector, by name. Adding one is an import and a list entry."""

from app.connectors.base import ToolSpec
from app.connectors.gmail import GmailConnector
from app.connectors.http import HttpConnector
from app.connectors.sheets import SheetsConnector
from app.connectors.slack import SlackConnector
from app.connectors.youtube import YouTubeConnector

CONNECTORS = [GmailConnector(), SheetsConnector(), SlackConnector(), YouTubeConnector(), HttpConnector()]

_TOOLS: dict[str, ToolSpec] = {}
_PROVIDER_OF: dict[str, str] = {}

for _connector in CONNECTORS:
    for _spec in _connector.tools():
        _TOOLS[_spec.name] = _spec
        _PROVIDER_OF[_spec.name] = _connector.provider


def builtin_tools() -> dict[str, ToolSpec]:
    return dict(_TOOLS)


def get_tool(name: str) -> ToolSpec | None:
    return _TOOLS.get(name)


def provider_for(tool_name: str) -> str | None:
    return _PROVIDER_OF.get(tool_name)


def catalog() -> list[dict]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "writes": spec.writes,
            "provider": _PROVIDER_OF[spec.name],
        }
        for spec in _TOOLS.values()
    ]


def known_providers() -> set[str]:
    return {c.provider for c in CONNECTORS}
