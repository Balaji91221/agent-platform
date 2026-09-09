"""The shape every built-in connector follows (plan NFR-6: adding one is one file)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class ToolSpec:
    """One callable tool. `writes` drives the can_write gate (plan FR-15)."""

    name: str
    description: str
    writes: bool
    schema: dict[str, Any]
    handler: Callable[..., Awaitable[Any]]


class ConnectionMissing(Exception):
    """The provider this tool needs has never been connected."""


class ConnectorError(Exception):
    """The provider answered, but with an error the model should read."""


def require_token(credential: str | None, label: str) -> str | None:
    """The bearer token for a call, or None in stub mode.

    Raises `ConnectionMissing` on the live path — a tool must never quietly run
    unauthenticated or hand the model sample data.
    """
    from app.config import settings
    from app.security.secrets import access_token

    if settings.CONNECTOR_STUBS:
        return None
    if not credential:
        raise ConnectionMissing(f"{label} is not connected — connect it on the Connections screen")
    return access_token(credential)


class Connector:
    provider: str = ""
    label: str = ""

    def tools(self) -> list[ToolSpec]:
        raise NotImplementedError


def tool(
    name: str, description: str, *, writes: bool = False, schema: dict | None = None
) -> Callable:
    """Mark a coroutine as a tool and carry its metadata."""

    def wrap(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        fn._tool = ToolSpec(  # type: ignore[attr-defined]
            name=name,
            description=description,
            writes=writes,
            schema=schema or {"type": "object", "properties": {}},
            handler=fn,
        )
        return fn

    return wrap


def collect(instance: Connector) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for attr in dir(instance):
        member = getattr(instance, attr)
        spec = getattr(member, "_tool", None)
        if spec is not None:
            specs.append(
                ToolSpec(
                    name=spec.name,
                    description=spec.description,
                    writes=spec.writes,
                    schema=spec.schema,
                    handler=member,
                )
            )
    return specs
