"""The lead's decision: one model call, no tools (plan NFR-10).

Job titles are free text — "Billing analyst", "Invoice watcher" and "Finance"
all mean the same thing to a person — so a model matches them without a keyword
table anyone has to maintain. Giving it no tools keeps it cheap and means a
wrong pick can never cause a side effect.

Three outcomes, all visible in the thread:

- ``handoff``  another teammate's job fits; a handoff card records why.
- ``self``     it is the lead's own job; the lead's agent runs it.
- ``reply``    small talk, a question about the team, thanks, or something
               nobody here can do; the lead answers in the thread, no run.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.models import TeamMessage, Teammate
from app.runtime.models_api import ModelProvider, get_provider
from app.team.context import transcript

# ``handoff`` is first on purpose: the fake provider answers with the first enum
# value and teammate 0, which lands in the keyword backstop below.
ACTIONS = ("handoff", "self", "reply")

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "teammate_id": {"type": "integer"},
        "reason": {"type": "string"},
        "reply": {"type": "string"},
    },
    "required": ["action", "teammate_id", "reason", "reply"],
    "additionalProperties": False,
}

SYSTEM = (
    "You lead a small team of AI agents that share one group chat with the person "
    "who owns them. Read the latest message and decide one of three things.\n"
    "1. handoff — a teammate's job clearly fits: set teammate_id to that teammate "
    "and write a one-line reason that names them by name and job title, e.g. "
    "\"Noor handles billing questions.\" Never mention ids.\n"
    "2. self — it is your own job: teammate_id 0, reason one line, e.g. "
    "\"Renewals are mine.\"\n"
    "3. reply — a greeting, thanks, a question about the team or who does what, "
    "or something nobody on the team can do: teammate_id 0 and write the reply "
    "yourself in `reply`, first person, one to three plain sentences, as the lead "
    "speaking to the owner. Say who does what when asked; say plainly what nobody "
    "can do rather than pretending.\n"
    "Prefer handoff or self for any real task. Answer only with the JSON object."
)


@dataclass
class Decision:
    action: str  # handoff | self | reply
    teammate_id: int | None
    reason: str
    reply: str = ""


def _roster_text(mates: list[Teammate]) -> str:
    return "\n".join(
        f"- id={m.id} · {m.display_name} · {m.job_title} · {m.description}" for m in mates
    )


def _prompt(
    message: str, lead: Teammate | None, others: list[Teammate], history: list[TeamMessage]
) -> str:
    me = (
        f"You are {lead.display_name}, {lead.job_title}. {lead.description}".strip()
        if lead
        else "You are the lead."
    )
    lines = transcript(history, ([lead] if lead else []) + others)
    recent = "\n".join(lines) if lines else "(nothing yet)"
    return (
        f"{me}\n\nTeammates you can hand work to:\n{_roster_text(others) or '(none)'}\n\n"
        f"Recent conversation, oldest first:\n{recent}\n\nLatest message:\n{message}"
    )


async def choose(
    message: str,
    candidates: list[Teammate],
    provider: ModelProvider | None = None,
    *,
    lead: Teammate | None = None,
    history: list[TeamMessage] | None = None,
) -> Decision:
    """Decide what happens to one message. Ids are validated against the roster."""
    provider = provider or get_provider(settings.LEAD_MODEL)
    prompt = _prompt(message, lead, candidates, history or [])

    try:
        raw = await provider.json_object(
            model=settings.LEAD_MODEL, system=SYSTEM, prompt=prompt, schema=DECISION_SCHEMA
        )
        action = str(raw.get("action") or "").strip().lower()
        chosen = int(raw.get("teammate_id") or 0)
        reason = str(raw.get("reason") or "").strip()
        reply = str(raw.get("reply") or "").strip()
    except Exception:  # noqa: BLE001 - a routing failure falls back, never 500s
        action, chosen, reason, reply = "", 0, "", ""

    valid = {m.id for m in candidates}
    if action == "handoff" and chosen in valid:
        return Decision("handoff", chosen, reason or "Closest match to the request.")
    if action == "self" and lead is not None:
        return Decision("self", lead.id, reason or "This one is mine.")
    if action == "reply" and reply:
        return Decision("reply", None, reason, reply)

    # The model declined, was unavailable, or named nobody real: a deterministic
    # backstop that can route work but never starts a run on a guess.
    return _fallback(message, lead, candidates)


def _fallback(message: str, lead: Teammate | None, candidates: list[Teammate]) -> Decision:
    match = _keyword_match(message, candidates)
    if match is not None:
        return Decision(
            "handoff",
            match.id,
            f"{match.display_name} is the closest match to the request out of "
            f"{len(candidates)} teammates.",
        )
    if lead is not None and _keyword_match(message, [lead]) is not None:
        return Decision("self", lead.id, "Closest match to my own job.")
    return Decision("reply", None, "", _who_does_what(lead, candidates))


def _who_does_what(lead: Teammate | None, candidates: list[Teammate]) -> str:
    """Said by the lead when nothing matched: what the team can actually do."""
    if not candidates and lead is None:
        return "There is nobody on the team yet, so I cannot pass this on."
    parts = [f"{m.display_name} handles {m.job_title.lower()}" for m in candidates]
    if lead is not None:
        parts.append(f"I ({lead.display_name}) handle {lead.job_title.lower()}")
    listing = "; ".join(parts)
    return (
        f"I'm not sure who should take this. On the team: {listing}. Mention one of "
        f"them with @ to hand it over, or tell me a bit more."
    )


def _keyword_match(message: str, candidates: list[Teammate]) -> Teammate | None:
    """Deterministic backstop used when the model declines or is unavailable."""
    words = {w.strip(".,!?") for w in message.lower().split() if len(w) >= 3}
    best, top = None, 0
    for mate in candidates:
        hay = f"{mate.job_title} {mate.description} {mate.display_name}".lower()
        score = sum(1 for w in words if w in hay)
        if score > top:
            best, top = mate, score
    return best
