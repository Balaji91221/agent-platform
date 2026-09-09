"""NVIDIA's OpenAI-compatible endpoint, for the open models it hosts.

Same request shape as OpenAI chat/completions, different base URL, key, and
model names. Kept in its own file so the Anthropic path stays untouched.

The wire format differs from Anthropic's in three ways this class absorbs, so
the executor never sees the difference:
  - tools are `{"type": "function", "function": {...}}`, not flat
  - a tool call comes back on the message, not as a content block
  - tool results are `{"role": "tool", ...}`, not a user block
"""

from __future__ import annotations

import asyncio
import json
import re
import logging
from typing import Any

import httpx

from app.config import settings
from app.exceptions.errors import UpstreamException
from app.runtime.models_api import ModelProvider, ModelTurn, ToolCall

logger = logging.getLogger(__name__)


def encode_tool_name(name: str) -> str:
    """OpenAI-style function names allow only [A-Za-z0-9_-]; ours carry dots and
    colons (gmail.list_unread, mcp:1.search_docs). Reversible, so a call comes
    back under the name the router knows."""
    return name.replace(".", "__").replace(":", "--")


_WIRE_NAME = re.compile(r"[A-Za-z0-9_\-]+")


def decode_tool_name(name: str) -> str:
    """Wire name -> registry name.

    Nemotron sometimes leaks its chat template's closing tag into the name
    (`gmail__list_unread\n</function`), so only the leading legal token counts;
    anything after it is template noise, not part of the tool.
    """
    match = _WIRE_NAME.match(name.strip())
    clean = match.group(0) if match else name
    return clean.replace("--", ":").replace("__", ".")


class NvidiaProvider(ModelProvider):
    def __init__(self) -> None:
        if not settings.NVIDIA_API_KEY:
            raise UpstreamException(
                "NVIDIA_API_KEY is not set — add it to .env to use MODEL_PROVIDER=nvidia"
            )
        self._url = settings.NVIDIA_BASE_URL.rstrip("/") + "/chat/completions"

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _model_id(name: str) -> str:
        return settings.MODEL_IDS.get(name, name)

    def _headers(self, stream: bool) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
            "Accept": "text/event-stream" if stream else "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _to_openai_messages(
        system: str, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Anthropic-shaped history -> OpenAI-shaped history."""
        out: list[dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})

        for message in messages:
            content = message.get("content")

            if isinstance(content, str):
                out.append({"role": message["role"], "content": content})
                continue

            # A list of blocks: text, tool_use, tool_result, or image.
            text_parts: list[dict[str, Any]] = []
            tool_calls: list[dict[str, Any]] = []
            emitted_tool_results = False

            for block in content or []:
                kind = block.get("type")

                if kind == "text":
                    text_parts.append({"type": "text", "text": block.get("text", "")})

                elif kind == "image_url":
                    # Passed through as-is; vision models take this shape.
                    text_parts.append(block)

                elif kind == "image":
                    source = block.get("source", {})
                    if source.get("type") == "base64":
                        url = f"data:{source.get('media_type')};base64,{source.get('data')}"
                    else:
                        url = source.get("url", "")
                    text_parts.append({"type": "image_url", "image_url": {"url": url}})

                elif kind == "tool_use":
                    tool_calls.append(
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": encode_tool_name(block["name"]),
                                "arguments": json.dumps(block.get("input") or {}),
                            },
                        }
                    )

                elif kind == "tool_result":
                    body = block.get("content")
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": body if isinstance(body, str) else json.dumps(body),
                        }
                    )
                    emitted_tool_results = True

            if tool_calls or text_parts:
                entry: dict[str, Any] = {"role": message["role"]}
                if text_parts:
                    only_text = all(p["type"] == "text" for p in text_parts)
                    entry["content"] = (
                        "".join(p["text"] for p in text_parts) if only_text else text_parts
                    )
                else:
                    entry["content"] = None
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                out.append(entry)
            elif not emitted_tool_results:
                out.append({"role": message["role"], "content": ""})

        return out

    @staticmethod
    def _to_openai_tools(tools: list[dict[str, Any]] | None) -> list[dict] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": encode_tool_name(t["name"]),
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema")
                    or {"type": "object", "properties": {}},
                },
            }
            for t in tools
        ]

    def _payload(
        self, model: str, messages: list[dict], tools: list[dict] | None, stream: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model_id(model),
            "messages": messages,
            "max_tokens": settings.NVIDIA_MAX_TOKENS,
            "temperature": settings.NVIDIA_TEMPERATURE,
            "stream": stream,
        }
        if settings.NVIDIA_SEED is not None:
            payload["seed"] = settings.NVIDIA_SEED
        if stream:
            # Otherwise a streamed reply carries no usage and the log says 0/0.
            payload["stream_options"] = {"include_usage": True}
        if settings.NVIDIA_THINKING:
            if model in settings.NVIDIA_REASONING_MODELS:
                payload["reasoning_effort"] = settings.NVIDIA_REASONING_EFFORT
        else:
            # Same two switches the builder uses: nemotron honours one, gpt-oss the other.
            payload["reasoning_effort"] = "low"
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    # ------------------------------------------------------------------ requests

    async def _post_streaming(self, payload: dict) -> dict[str, Any]:
        """Read the SSE stream and rebuild one message from the deltas.

        Overload is retried once: NVIDIA reports it either as an HTTP 503 or —
        after a 200 has already started — as a `data: {"error": ...}` frame.
        """
        for attempt in (1, 2):
            try:
                return await self._stream_once(payload)
            except UpstreamException as exc:
                if attempt == 2 or not exc.retryable:
                    raise
                await asyncio.sleep(self.RETRY_DELAY)
        raise AssertionError("unreachable")

    @staticmethod
    def _raise_if_error_frame(event: dict[str, Any]) -> None:
        """An error delivered inside the stream is still an error, not an empty answer."""
        err = event.get("error")
        if not err:
            return
        code = err.get("code") if isinstance(err, dict) else None
        message = err.get("message") if isinstance(err, dict) else str(err)
        try:
            status = int(code)
        except (TypeError, ValueError):
            status = 503
        raise UpstreamException(
            f"NVIDIA {status}: {message}", retryable=status >= 500 or status == 429
        )

    async def _stream_once(self, payload: dict) -> dict[str, Any]:
        text = ""
        calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST", self._url, headers=self._headers(True), json=payload
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode()
                    raise self._http_error(response.status_code, body)

                async for raw in response.aiter_lines():
                    if not raw or not raw.startswith("data:"):
                        continue
                    chunk = raw[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        event = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue

                    self._raise_if_error_frame(event)
                    if event.get("usage"):
                        usage = event["usage"]
                    for choice in event.get("choices", []):
                        delta = choice.get("delta") or {}
                        text += delta.get("content") or ""
                        for call in delta.get("tool_calls") or []:
                            slot = calls.setdefault(
                                call.get("index", 0),
                                {"id": "", "name": "", "arguments": ""},
                            )
                            if call.get("id"):
                                slot["id"] = call["id"]
                            fn = call.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]

        return {"text": text, "calls": list(calls.values()), "usage": usage}

    # NVIDIA's shared endpoint sheds load with 503s that clear in a second or two.
    RETRY_STATUSES = {429, 502, 503, 504}
    RETRY_DELAY = 1.5

    @staticmethod
    def _http_error(status: int, body: str) -> UpstreamException:
        """Classify a non-2xx answer.

        Seen live: the gateway answers a known model with a bare 404 and an
        empty body about 1 call in 6, then serves the next call fine. A 4xx
        *with* a body ("model not found", "invalid function name") is the
        caller's problem and must not be retried.
        """
        text = body.strip()
        transient = status >= 500 or status == 429 or not text
        shown = text[:400] if text else "(empty body — gateway hiccup)"
        return UpstreamException(f"NVIDIA {status}: {shown}", retryable=transient)

    def _should_retry_now(self, status: int, body: str) -> bool:
        return status in self.RETRY_STATUSES or (status >= 400 and not body.strip())

    async def _post_once(self, payload: dict) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(self._url, headers=self._headers(False), json=payload)
            if self._should_retry_now(response.status_code, response.text):
                await asyncio.sleep(self.RETRY_DELAY)
                response = await client.post(
                    self._url, headers=self._headers(False), json=payload
                )
        if response.status_code >= 400:
            raise self._http_error(response.status_code, response.text)

        body = response.json()
        self._raise_if_error_frame(body)
        message = (body.get("choices") or [{}])[0].get("message") or {}
        calls = [
            {
                "id": c.get("id", ""),
                "name": (c.get("function") or {}).get("name", ""),
                "arguments": (c.get("function") or {}).get("arguments", "{}"),
            }
            for c in (message.get("tool_calls") or [])
        ]
        return {
            "text": message.get("content") or "",
            "calls": calls,
            "usage": body.get("usage") or {},
        }

    # ------------------------------------------------------------------ interface

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelTurn:
        payload = self._payload(
            model,
            self._to_openai_messages(system, messages),
            self._to_openai_tools(tools),
            settings.NVIDIA_STREAM,
        )
        result = (
            await self._post_streaming(payload)
            if settings.NVIDIA_STREAM
            else await self._post_once(payload)
        )

        usage = result["usage"]
        return ModelTurn(
            text=result["text"],
            tool_calls=[
                ToolCall(
                    id=c["id"] or f"call_{i}",
                    name=decode_tool_name(c["name"]),
                    arguments=_safe_json(c["arguments"]),
                )
                for i, c in enumerate(result["calls"])
                if c["name"]
            ],
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    async def json_object(
        self, *, model: str, system: str, prompt: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Structured output. Streaming is off here — the whole object is wanted."""
        payload = self._payload(
            model,
            [
                {
                    "role": "system",
                    "content": f"{system}\n\nAnswer with JSON matching this schema:\n"
                    f"{json.dumps(schema)}\nReturn JSON only, no prose.",
                },
                {"role": "user", "content": prompt},
            ],
            None,
            False,
        )
        payload["response_format"] = {"type": "json_object"}
        # A structured answer is short. A reasoning model left at 16k tokens can
        # spend minutes thinking before it writes the JSON.
        payload["max_tokens"] = min(payload["max_tokens"], settings.NVIDIA_JSON_MAX_TOKENS)
        payload["temperature"] = 0.2  # a decision, not a story
        # Reasoning models think for thousands of characters before writing the
        # JSON and run out of budget first (measured: 38s and no JSON, versus 6s
        # with thinking off). Nemotron honours chat_template_kwargs, gpt-oss
        # honours reasoning_effort; each ignores the other.
        payload["reasoning_effort"] = "low"
        payload["chat_template_kwargs"] = {"enable_thinking": False}

        result = await self._post_once(payload)
        return _safe_json(result["text"], strict=True)


def _safe_json(raw: str | dict, strict: bool = False) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string; models sometimes fence them."""
    if isinstance(raw, dict):
        return raw
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        if strict:
            raise
        logger.warning("could not parse tool arguments: %s", text[:120])
        return {}
