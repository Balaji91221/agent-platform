"""A non-task message gets a real chat answer, not the JSON call's terse field."""

from app.builder.draft import build
from app.runtime.models_api import ModelProvider, ModelTurn


class TwoStage(ModelProvider):
    """JSON call says 'reply'; the chat call gives the real answer."""

    def __init__(self, chat_text="**Claude** is a family of models by Anthropic.", chat_fails=False):
        self.chat_text = chat_text
        self.chat_fails = chat_fails
        self.chat_messages = None

    async def json_object(self, *, model, system, prompt, schema, **kw):
        return {"intent": "reply", "reply": "Claude models are available here."}

    async def complete(self, *, model, system, messages, tools=None):
        if self.chat_fails:
            raise RuntimeError("upstream down")
        self.chat_messages = messages
        assert "Facts about this platform" in system
        return ModelTurn(text=self.chat_text)


async def test_reply_comes_from_the_chat_call_with_history():
    p = TwoStage()
    out = await build("what is claude", provider=p, models=["claude-sonnet-5"],
                      history=[{"role": "user", "text": "hi"}, {"role": "assistant", "text": "Hello!"}])
    assert out.kind == "reply" and out.text == "**Claude** is a family of models by Anthropic."
    assert [m["role"] for m in p.chat_messages] == ["user", "assistant", "user"]
    assert p.chat_messages[-1]["content"] == "what is claude"


async def test_json_reply_is_the_fallback_when_chat_fails():
    out = await build("what is claude", provider=TwoStage(chat_fails=True), models=["claude-sonnet-5"])
    assert out.kind == "reply" and out.text == "Claude models are available here."


async def test_a_repeated_invite_is_still_cut_from_the_chat_answer():
    p = TwoStage(chat_text="Claude is by Anthropic. What task would you like the agent to do?")
    hist = [{"role": "assistant", "text": "Hi! What task would you like the agent to do?"}]
    out = await build("claude", provider=p, models=["claude-sonnet-5"], history=hist)
    assert out.text == "Claude is by Anthropic."
