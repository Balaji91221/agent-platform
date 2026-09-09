"""Plain words in — a draft agent out, or a reply when there is no task yet (FR-19).

Not every message describes an agent. "hi" and "tell me claude" get a
conversational answer; "summarise my inbox each morning" gets a draft. One
model call decides which, so the chat feels like a chat rather than a form
that mislabels greetings as agent names.

The draft is validated against the agent schema. On a malformed answer it asks
once more with the error; if that fails too, the caller gets a skeleton draft
with the user's text in the description rather than an error screen.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.exceptions.errors import ValidationException
from app.connectors.registry import catalog
from app.runtime.models_api import ModelProvider, get_provider
from app.scheduler.cron import validate_cron, zone


def _tool_lines() -> str:
    return "\n".join(f"- {t['name']}: {t['description']}" for t in catalog())


def _tool_names() -> list[str]:
    return [t["name"] for t in catalog()]


def _facts() -> str:
    """What the assistant is allowed to say about this platform. Kept factual so
    a question like "chatgpt?" gets a true answer, not a guess."""
    models = ", ".join(settings.MODEL_IDS)
    return (
        "Facts about this platform (Relay): it runs scheduled AI agents that act "
        "through the user's own accounts (Gmail, Google Sheets, Slack, YouTube, custom "
        "HTTP, MCP servers). Available models: " + models + ". The default is "
        "nemotron-3-super (NVIDIA-hosted, fast). Claude models are available when an "
        "Anthropic key is configured by the operator in the backend .env — there is no "
        "settings page for keys in the app. ChatGPT / OpenAI / GPT-4 models are NOT available "
        "here. Agents run on a cron schedule or by hand, can be put on a team, and "
        "notify by email, Slack DM or webhook."
    )


SYSTEM = (
    "You help someone build a scheduled AI agent by chatting. Decide first: does the "
    "latest message (read with the conversation so far) describe a job an agent should "
    "do on a schedule? If it does, set intent to 'draft' and write a short name in "
    "plain words (like 'Daily unread mail to Slack', never snake_case), a "
    "one-line description, a system prompt for who the agent is, a user prompt for the "
    "task, a cron expression, model 'nemotron-3-super' unless the user names another "
    "available one (a model that is not available here, like GPT-4 or ChatGPT, still "
    "gets a draft on the default model — say so in the description), "
    "and the tool names it needs (prefer read-only tools). If it does not, set intent "
    "to 'reply' and answer the message itself in one to three sentences: answer a "
    "question truthfully using the facts below, respond to a greeting naturally, and "
    "only then, if no task has been mentioned yet, invite them to describe one — in "
    "your own words, never the same sentence twice in a conversation. Do not answer a "
    "question with a question. If the user names a company or product (Google, Slack, "
    "YouTube, Gmail, Notion), say what an agent here can do with it through its "
    "connector — it is not a model. Leave the draft fields empty for a reply. Only use tool "
    "names from this list, exactly as written; if none fit, leave tools empty:\n"
    + _tool_lines()
    + "\n\n"
    + _facts()
)

DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["draft", "reply"]},
        "reply": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "system_prompt": {"type": "string"},
        "user_prompt": {"type": "string"},
        "model": {
            "type": "string",
            "enum": list(settings.MODEL_IDS),
        },
        "cron": {"type": "string"},
        "timezone": {"type": "string"},
        # The enum pins the model to tools that exist; _coerce is the backstop for
        # providers whose JSON mode does not enforce the schema.
        "tools": {"type": "array", "items": {"type": "string", "enum": _tool_names()}},
    },
    "required": [
        "intent",
        "reply",
        "name",
        "description",
        "system_prompt",
        "user_prompt",
        "model",
        "cron",
        "timezone",
        "tools",
    ],
    "additionalProperties": False,
}


class AgentDraft(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    system_prompt: str = ""
    user_prompt: str = ""
    model: str = "nemotron-3-super"
    cron: str = "0 9 * * *"
    timezone: str = "Asia/Kolkata"
    tools: list[str] = Field(default_factory=list)


class Reply(BaseModel):
    kind: Literal["reply"] = "reply"
    text: str


class Drafted(BaseModel):
    kind: Literal["draft"] = "draft"
    draft: AgentDraft


BuilderResult = Reply | Drafted

_NUDGE = (
    "Tell me what the agent should do and when — for example: "
    "\"summarise my unread email every morning and post it to Slack\"."
)

# Words that mean "do something for me on a schedule". A message with none of
# these and few words is a chat message, not a job description.
_TASK_WORDS = re.compile(
    r"\b(summari[sz]e|watch|check|monitor|post|send|remind|triage|report|fetch|"
    r"read|scan|flag|escalate|label|draft|notify|alert|pull|sync|every|daily|"
    r"weekly|hourly|morning|evening|when|each|inbox|email|mail|slack|ticket|"
    r"invoice|calendar|sheet|issue)\b",
    re.I,
)
_GREETING = re.compile(r"^\s*(hi|hello|hey|yo|hola|thanks|thank you|ok|okay|test)\b", re.I)


def looks_like_task(text: str) -> bool:
    """The fake provider's stand-in for the model's intent decision."""
    words = text.strip().split()
    if _GREETING.match(text) and len(words) <= 3:
        return False
    if _TASK_WORDS.search(text):
        return True
    # A question, or something too short to be a job, is a chat message.
    return len(words) >= 8 and not text.strip().endswith("?")


def _skeleton(text: str, timezone: str | None = None) -> AgentDraft:
    return AgentDraft(
        timezone=timezone or "Asia/Kolkata",
        name=text.strip()[:40] or "New agent",
        description=text.strip()[:200],
        system_prompt="",
        user_prompt=text.strip(),
    )


def _mentions_utc(text: str) -> bool:
    return bool(re.search(r"\b(utc|gmt)\b", text, re.IGNORECASE))


def _coerce(raw: dict, user_tz: str | None = None, text: str = "") -> AgentDraft:
    draft = AgentDraft.model_validate(raw)
    validate_cron(draft.cron)
    if draft.model not in settings.MODEL_IDS:
        draft.model = settings.BUILDER_MODEL
    # A made-up tool would fail on Create, so it is dropped here instead.
    known = set(_tool_names())
    draft.tools = [t for t in draft.tools if t in known]
    # "9am" means 9am where the user is. Models default to UTC unless told; the
    # browser's zone wins unless the user actually asked for UTC.
    if user_tz and (not draft.timezone or (draft.timezone == "UTC" and not _mentions_utc(text))):
        draft.timezone = user_tz
    elif not draft.timezone:
        draft.timezone = "Asia/Kolkata"
    try:
        zone(draft.timezone)
    except ValidationException:
        draft.timezone = user_tz or "Asia/Kolkata"
    return draft


_INVITE = re.compile(
    r"(what (task|would you like|should the agent|can i help)|would you like (to|me to)|"
    r"tell me (what|the task)|describe (a|the|what|your)|do you have a (specific )?task|"
    r"want to (try|build|set up|create)|let me know (the|what|if)|"
    r"i(\u2019|')ll (help|walk|guide)|ready to build|shall we)",
    re.IGNORECASE,
)


def _already_invited(history: list[dict] | None) -> bool:
    return any(
        h.get("role") == "assistant" and _INVITE.search(h.get("text") or "")
        for h in (history or [])
    )


def trim_repeated_invite(reply: str, history: list[dict] | None) -> str:
    """Drop a trailing "what would you like the agent to do?" once it has been asked.

    Small models append the same invite to every turn no matter what the prompt
    says; after the first time it reads as not listening, so it is cut here.
    """
    if not _already_invited(history):
        return reply
    sentences = re.split(r"(?<=[.!?])\s+", reply.strip())
    while len(sentences) > 1 and _INVITE.search(sentences[-1]):
        sentences.pop()
    return " ".join(sentences).strip() or reply


CHAT_SYSTEM = (
    "You are the assistant inside Relay, a platform for scheduled AI agents. Answer "
    "the way a good AI assistant answers: directly, in natural prose, with real "
    "substance — explain, compare, give examples. Use markdown lightly (bold, short "
    "lists) when it helps. Keep it under about 150 words unless the question needs "
    "more. Use the facts below whenever the question touches this platform, and be "
    "clear about what is not available here. Do not end with a stock question; only "
    "invite the user to describe an agent if that has not been suggested yet in the "
    "conversation. When describing what an agent can do with a service, only name "
    "abilities that appear in the tool list below — never invent others (no "
    "labelling, forwarding, calendar, drive, etc. unless a tool says so).\n\n"
)
CHAT_TIMEOUT_SECONDS = 20


def _chat_facts() -> str:
    return _facts() + "\n\nTools agents can use (name — what it does):\n" + _tool_lines()


async def _chat_reply(
    provider: ModelProvider, model: str, text: str, history: list[dict] | None
) -> str | None:
    """A real chat answer for a non-task message.

    The JSON draft call is tuned for structure (low temperature, tight token
    budget) and its `reply` field reads like a form. This is the same message
    asked as ordinary chat, so the answer reads like a model, not a template.
    """
    messages = [
        {"role": "user" if h.get("role") == "user" else "assistant", "content": h["text"]}
        for h in (history or [])[-12:]
        if h.get("text")
    ] + [{"role": "user", "content": text}]
    try:
        turn = await asyncio.wait_for(
            provider.complete(model=model, system=CHAT_SYSTEM + _chat_facts(), messages=messages),
            timeout=CHAT_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 - the JSON reply is the fallback
        return None
    answer = (turn.text or "").strip()
    return answer or None


def _transcript(history: list[dict] | None, text: str) -> str:
    """The prompt the model sees: prior turns, then the message to answer."""
    turns = [h for h in (history or []) if h.get("text")][-12:]
    if not turns:
        return text
    lines = [f"{'User' if h.get('role') == 'user' else 'Assistant'}: {h['text']}" for h in turns]
    return "Conversation so far:\n" + "\n".join(lines) + f"\n\nLatest message from the user:\n{text}"


async def build(
    text: str,
    provider: ModelProvider | None = None,
    models: list[str] | None = None,
    timezone: str | None = None,
    history: list[dict] | None = None,
) -> BuilderResult:
    """Race every model at once; the first usable answer wins, the rest are cancelled.

    On a shared endpoint the fastest model changes minute to minute. Asking them
    in sequence sums the timeouts; asking together costs the fastest one only.
    """
    from app.runtime.models_api import FakeProvider

    chain = models or [settings.BUILDER_MODEL, *settings.BUILDER_FALLBACK_MODELS]
    providers = {m: (provider or get_provider(m)) for m in chain}

    # The fake provider cannot judge intent, so a keyword check stands in.
    fake = any(isinstance(p, FakeProvider) for p in providers.values())
    if fake and not looks_like_task(text):
        return Reply(text=f"Hi! {_NUDGE}")

    tasks = {asyncio.create_task(_ask(providers[m], m, text, timezone, history)): m for m in chain}
    tasks_model = dict(tasks)
    # Started now so a reply costs max(json, chat), not their sum; cancelled if
    # the message turns out to be a task.
    chat_task = (
        None if fake else asyncio.create_task(_chat_reply(providers[chain[0]], chain[0], text, history))
    )
    deadline = asyncio.get_running_loop().time() + settings.BUILDER_TIMEOUT_SECONDS
    try:
        while tasks:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            done, _ = await asyncio.wait(
                tasks, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                break
            for task in done:
                tasks.pop(task)
                answer = task.result()
                if answer is not None:
                    if isinstance(answer, Reply) and chat_task is not None:
                        remaining = max(0.5, deadline - asyncio.get_running_loop().time())
                        try:
                            chat = await asyncio.wait_for(chat_task, timeout=remaining)
                        except Exception:  # noqa: BLE001 - keep the JSON reply
                            chat = None
                        if chat:
                            answer = Reply(text=trim_repeated_invite(chat, history))
                    return answer
    finally:
        for task in tasks:
            task.cancel()
        if chat_task is not None and not chat_task.done():
            chat_task.cancel()

    return _fallback(text, timezone)


async def _ask(
    provider: ModelProvider,
    model: str,
    text: str,
    timezone: str | None = None,
    history: list[dict] | None = None,
) -> BuilderResult | None:
    """One model, up to two tries. None means it did not answer usably."""
    base = _transcript(history, text)
    prompt = f"{base}\n\n(The user's timezone is {timezone}.)" if timezone else base
    for attempt in (1, 2):
        try:
            raw = await provider.json_object(
                model=model, system=SYSTEM, prompt=prompt, schema=DRAFT_SCHEMA
            )
            if raw.get("intent") == "reply":
                answer = str(raw.get("reply") or "").strip() or _NUDGE
                return Reply(text=trim_repeated_invite(answer, history))
            return Drafted(draft=_coerce(raw, timezone, text))
        except (ValidationError, ValueError, KeyError) as exc:
            if attempt == 2:
                return None
            # Ask once more, telling it exactly what was wrong.
            prompt = f"{base}\n\nYour previous answer was invalid: {exc}. Try again."
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - this model is out; another may still answer
            return None
    return None


def _fallback(text: str, timezone: str | None = None) -> BuilderResult:
    """The model did not answer. A task still gets a rough draft to edit; anything
    else gets told the truth rather than being turned into an agent called "hi"."""
    if looks_like_task(text):
        return Drafted(draft=_skeleton(text, timezone))
    return Reply(
        text="I couldn't reach the model just now, so I have nothing to draft yet. "
        + _NUDGE
    )
