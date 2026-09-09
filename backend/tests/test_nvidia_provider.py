"""The NVIDIA provider's wire-format translation.

These run offline: they check the shape we send and how we read a reply, which
is where an OpenAI-compatible provider actually differs from Anthropic.
"""

import json

import pytest

from app.config import settings
from app.runtime.nvidia_provider import NvidiaProvider, _safe_json


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "test-key")
    return NvidiaProvider()


def test_ui_names_map_to_real_catalogue_ids():
    assert settings.MODEL_IDS["nemotron-3-super"] == "nvidia/nemotron-3-super-120b-a12b"
    assert settings.MODEL_IDS["gpt-oss-20b"] == "openai/gpt-oss-20b"
    for name in settings.NVIDIA_MODELS:
        assert name in settings.MODEL_IDS, f"{name} has no catalogue id"


def test_an_nvidia_model_routes_to_nvidia_whatever_the_default(monkeypatch):
    """A workspace can mix Claude and open models at the same time."""
    from app.runtime.models_api import FakeProvider, get_provider

    monkeypatch.setattr(settings, "MODEL_PROVIDER", "fake")
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "test-key")

    assert isinstance(get_provider("claude-sonnet-5"), FakeProvider)
    assert isinstance(get_provider("kimi-k3"), NvidiaProvider)


def test_system_prompt_becomes_a_system_message(provider):
    out = provider._to_openai_messages("be brief", [{"role": "user", "content": "hi"}])
    assert out[0] == {"role": "system", "content": "be brief"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_tool_use_block_becomes_an_openai_tool_call(provider):
    out = provider._to_openai_messages(
        "",
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "c1", "name": "gmail.send", "input": {"to": "a@b.c"}}
                ],
            }
        ],
    )
    call = out[0]["tool_calls"][0]
    assert call["id"] == "c1"
    assert call["function"]["name"] == "gmail__send"  # encoded for the wire
    assert json.loads(call["function"]["arguments"]) == {"to": "a@b.c"}


def test_tool_result_becomes_a_tool_role_message(provider):
    out = provider._to_openai_messages(
        "",
        [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "ok"}]}],
    )
    assert out[0] == {"role": "tool", "tool_call_id": "c1", "content": "ok"}


def test_image_blocks_survive_for_vision_models(provider):
    out = provider._to_openai_messages(
        "",
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {"type": "image_url", "image_url": {"url": "https://example/x.jpg"}},
                ],
            }
        ],
    )
    kinds = [part["type"] for part in out[0]["content"]]
    assert kinds == ["text", "image_url"]


def test_base64_images_are_converted_to_a_data_url(provider):
    out = provider._to_openai_messages(
        "",
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
                    }
                ],
            }
        ],
    )
    assert out[0]["content"][0]["image_url"]["url"] == "data:image/png;base64,QUJD"


def test_tools_are_wrapped_in_the_function_envelope(provider):
    wrapped = provider._to_openai_tools(
        [{"name": "gmail.send", "description": "d", "input_schema": {"type": "object"}}]
    )
    assert wrapped[0]["type"] == "function"
    assert wrapped[0]["function"]["name"] == "gmail__send"  # encoded for the wire


def test_thinking_is_off_for_runs_by_default(provider):
    for model in ("nemotron-3-super", "kimi-k3"):
        payload = provider._payload(model, [], None, True)
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        assert payload["reasoning_effort"] == "low"


def test_thinking_can_be_turned_back_on(provider, monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_THINKING", True)
    reasoning = provider._payload("kimi-k3", [], None, False)
    plain = provider._payload("nemotron-3-super", [], None, False)
    assert reasoning["reasoning_effort"] == settings.NVIDIA_REASONING_EFFORT
    assert "reasoning_effort" not in plain
    assert "chat_template_kwargs" not in plain


def test_payload_uses_the_catalogue_id_not_the_ui_name(provider):
    assert provider._payload("kimi-k3", [], None, True)["model"] == "moonshotai/kimi-k3"


def test_tool_arguments_survive_a_fenced_json_reply():
    assert _safe_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _safe_json("") == {}
    assert _safe_json("not json") == {}, "a bad reply must not kill the run"


def test_a_missing_key_fails_loudly(monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "")
    from app.exceptions.errors import UpstreamException

    with pytest.raises(UpstreamException):
        NvidiaProvider()


async def test_json_object_retries_once_on_overload(provider, monkeypatch):
    """A 503 clears in a second; one retry turns it into an answer, not an error."""
    import httpx

    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": {"message": "Service temporarily overloaded"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"intent\": \"reply\"}"}}]})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
    monkeypatch.setattr(NvidiaProvider, "RETRY_DELAY", 0)

    out = await provider.json_object(model="nemotron-3-super", system="s", prompt="hi", schema={})
    assert out == {"intent": "reply"} and len(attempts) == 2


async def test_json_calls_turn_thinking_off(provider, monkeypatch):
    """The whole latency problem: a structured answer must not wait on a monologue."""
    import httpx

    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    await provider.json_object(model="nemotron-3-super", system="s", prompt="p", schema={})
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent["reasoning_effort"] == "low"
    assert sent["max_tokens"] <= settings.NVIDIA_JSON_MAX_TOKENS


def test_tool_names_are_made_legal_for_the_wire_and_restored():
    from app.runtime.nvidia_provider import decode_tool_name, encode_tool_name

    for original in ["gmail.list_unread", "mcp:1.search_docs", "http.get", "plain_name"]:
        wire = encode_tool_name(original)
        assert all(c.isalnum() or c in "_-" for c in wire), wire
        assert decode_tool_name(wire) == original


def test_a_leaked_template_tag_is_stripped_from_the_tool_name():
    """Seen live on nemotron-3-super: the name arrived as 'gmail__list_unread\\n</function'."""
    from app.runtime.nvidia_provider import decode_tool_name

    assert decode_tool_name("gmail__list_unread\n</function") == "gmail.list_unread"
    assert decode_tool_name("mcp--1__search </function {}") == "mcp:1.search"


def test_wrapped_tools_use_the_wire_name(provider):
    wrapped = provider._to_openai_tools([{"name": "gmail.list_unread", "description": "d", "input_schema": {}}])
    assert wrapped[0]["function"]["name"] == "gmail__list_unread"


async def test_tool_calls_come_back_under_the_original_name(provider, monkeypatch):
    import httpx

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "function": {"name": "mcp--1__search_docs", "arguments": "{\"q\": \"x\"}"}}]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "NVIDIA_STREAM", False)

    turn = await provider.complete(model="nemotron-3-super", system="", messages=[{"role": "user", "content": "hi"}],
                                   tools=[{"name": "mcp:1.search_docs", "description": "", "input_schema": {}}])
    assert turn.tool_calls[0].name == "mcp:1.search_docs"
    assert turn.tool_calls[0].arguments == {"q": "x"}


def test_streamed_requests_ask_for_usage(provider):
    assert provider._payload("nemotron-3-super", [], None, True)["stream_options"] == {"include_usage": True}
    assert "stream_options" not in provider._payload("nemotron-3-super", [], None, False)


async def test_an_error_frame_inside_a_200_stream_is_an_error(provider, monkeypatch):
    """Overload arrives mid-stream as data: {"error": ...}; it must not read as an empty answer."""
    import httpx
    from app.exceptions.errors import UpstreamException

    hits = []

    def handler(request):
        hits.append(1)
        body = 'data: {"error": {"message": "Service temporarily overloaded", "code": 503}}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(NvidiaProvider, "RETRY_DELAY", 0)
    monkeypatch.setattr(settings, "NVIDIA_STREAM", True)

    with pytest.raises(UpstreamException) as exc:
        await provider.complete(model="nemotron-3-super", system="", messages=[{"role": "user", "content": "hi"}])
    assert exc.value.retryable is True
    assert len(hits) == 2, "one retry on overload, then give up to the run-level retry"


async def test_a_stream_that_recovers_on_retry_returns_the_answer(provider, monkeypatch):
    import httpx

    hits = []

    def handler(request):
        hits.append(1)
        if len(hits) == 1:
            return httpx.Response(200, content='data: {"error": {"code": 503, "message": "overloaded"}}\n\n',
                                  headers={"content-type": "text/event-stream"})
        body = ('data: {"choices": [{"delta": {"content": "All good"}}]}\n\n'
                'data: {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(NvidiaProvider, "RETRY_DELAY", 0)
    monkeypatch.setattr(settings, "NVIDIA_STREAM", True)

    turn = await provider.complete(model="nemotron-3-super", system="", messages=[{"role": "user", "content": "hi"}])
    assert turn.text == "All good" and turn.input_tokens == 5 and len(hits) == 2


async def test_an_empty_body_404_is_retried_and_then_succeeds(provider, monkeypatch):
    """Seen live: 1 call in 6 to a working model got a bare 404 with no body."""
    import httpx

    hits = []

    def handler(request):
        hits.append(1)
        if len(hits) == 1:
            return httpx.Response(404, content=b"")
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Ok"}}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 1}})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(NvidiaProvider, "RETRY_DELAY", 0)
    monkeypatch.setattr(settings, "NVIDIA_STREAM", False)

    turn = await provider.complete(model="nemotron-3-super", system="", messages=[{"role": "user", "content": "hi"}])
    assert turn.text == "Ok" and len(hits) == 2


def test_http_error_classification():
    from app.runtime.nvidia_provider import NvidiaProvider

    empty = NvidiaProvider._http_error(404, "")
    assert empty.retryable and "empty body" in str(empty)
    real_404 = NvidiaProvider._http_error(404, '{"error": "model not found"}')
    assert not real_404.retryable
    bad_request = NvidiaProvider._http_error(400, '{"error": "invalid function name"}')
    assert not bad_request.retryable
    assert NvidiaProvider._http_error(503, "").retryable and NvidiaProvider._http_error(429, "x").retryable


async def test_an_empty_body_404_is_retried_on_the_streaming_path_too(provider, monkeypatch):
    """The worker streams by default (NVIDIA_STREAM=True); same hiccup, same recovery."""
    import httpx

    hits = []

    def handler(request):
        hits.append(1)
        if len(hits) == 1:
            return httpx.Response(404, content=b"")
        body = ('data: {"choices": [{"delta": {"content": "Ok"}}]}\n\n'
                'data: {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(NvidiaProvider, "RETRY_DELAY", 0)
    monkeypatch.setattr(settings, "NVIDIA_STREAM", True)

    turn = await provider.complete(model="nemotron-3-super", system="", messages=[{"role": "user", "content": "hi"}])
    assert turn.text == "Ok" and len(hits) == 2
