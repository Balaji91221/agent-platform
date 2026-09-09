"""The builder answers the message it was given, with the conversation in view."""

from app.builder.draft import SYSTEM, _transcript, build
from app.runtime.models_api import ModelProvider


class Recording(ModelProvider):
    def __init__(self):
        self.prompts = []

    async def json_object(self, *, model, system, prompt, schema, **kw):
        self.prompts.append(prompt)
        return {"intent": "reply", "reply": "ok"}

    async def complete(self, **kw):  # pragma: no cover - not used here
        raise NotImplementedError


def test_system_prompt_carries_platform_facts_and_bans_the_stock_question():
    assert "ChatGPT / OpenAI / GPT-4 models are NOT available" in SYSTEM
    assert "nemotron-3-super" in SYSTEM
    assert "never the same sentence twice" in SYSTEM
    assert "Do not answer a question with a question" in SYSTEM


def test_transcript_puts_prior_turns_before_the_latest_message():
    out = _transcript([{"role": "user", "text": "hi"}, {"role": "assistant", "text": "Hello!"}], "claude?")
    assert out.startswith("Conversation so far:\nUser: hi\nAssistant: Hello!")
    assert out.endswith("Latest message from the user:\nclaude?")
    assert _transcript([], "hi") == "hi"


async def test_history_reaches_the_model(monkeypatch):
    recorder = Recording()
    result = await build(
        "and post it to Slack",
        provider=recorder,
        models=["claude-sonnet-5"],
        history=[{"role": "user", "text": "summarise my unread mail every morning"}],
    )
    assert result.kind == "reply"
    assert "summarise my unread mail every morning" in recorder.prompts[0]
    assert recorder.prompts[0].rstrip().endswith("and post it to Slack")


async def test_blank_text_is_rejected(user):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/builder/draft", json={"text": "   \n "}, headers={"X-User-Id": str(user.id)})
    assert r.status_code == 422 and "say something" in r.text


def test_unavailable_model_still_drafts_on_the_default():
    assert "still gets a draft on the default model" in SYSTEM
