"""The only place that talks to a model.

Two providers behind one interface. "anthropic" calls the real API; "fake"
replays canned turns so the whole platform — runs, retries, streaming, team
routing, the chat builder — is verifiable with no API key and no spend.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.config import settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ModelTurn:
    """One model reply: either text, or tool calls to run."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class ModelProvider:
    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        raise NotImplementedError

    async def json_object(
        self, *, model: str, system: str, prompt: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError


class FakeProvider(ModelProvider):
    """Deterministic stand-in. Calls the first allowed tool once, then answers."""

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        already_called = any(
            isinstance(m.get("content"), list)
            and any(b.get("type") == "tool_result" for b in m["content"])
            for m in messages
        )
        if tools and not already_called:
            first = tools[0]
            return ModelTurn(
                tool_calls=[ToolCall(id="call_1", name=first["name"], arguments={})],
                input_tokens=120,
                output_tokens=18,
            )
        return ModelTurn(
            text="Done. (fake provider — set MODEL_PROVIDER=anthropic for real output)",
            input_tokens=140,
            output_tokens=24,
        )

    async def json_object(
        self, *, model: str, system: str, prompt: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Fill the schema's required fields with plausible values."""
        from app.runtime.fake_json import fake_for_schema

        return fake_for_schema(schema, prompt)


class AnthropicProvider(ModelProvider):
    def __init__(self) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY or None)

    @staticmethod
    def _model_id(name: str) -> str:
        return settings.MODEL_IDS.get(name, name)

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        kwargs: dict[str, Any] = {
            "model": self._model_id(model),
            "max_tokens": 16000,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)

        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [
            # Tool inputs are parsed JSON from the SDK; never string-match them.
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
            for b in response.content
            if b.type == "tool_use"
        ]
        return ModelTurn(
            text=text,
            tool_calls=calls,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    async def json_object(
        self, *, model: str, system: str, prompt: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._client.messages.create(
            model=self._model_id(model),
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)


def get_provider(model: str | None = None) -> ModelProvider:
    """Pick the provider. A model that belongs to NVIDIA routes there regardless
    of the default, so one workspace can mix Claude and open models."""
    if model and model in settings.NVIDIA_MODELS:
        from app.runtime.nvidia_provider import NvidiaProvider

        return NvidiaProvider()
    if settings.MODEL_PROVIDER == "anthropic":
        return AnthropicProvider()
    if settings.MODEL_PROVIDER == "nvidia":
        from app.runtime.nvidia_provider import NvidiaProvider

        return NvidiaProvider()
    return FakeProvider()
