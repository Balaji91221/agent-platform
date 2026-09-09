"""What a teammate is told when a message from the room reaches its agent.

The agent keeps its own system prompt (that is what makes it a billing analyst
or an inbox triager). This module builds the *user* turn: who the teammate is
in this room, what was said recently, and the one message it should answer.
Without it the agent sees "Sort out the Acme renewal" with no idea that it is
Ravi, that Ada spoke two lines earlier, or that a person is waiting in a chat.
"""

from __future__ import annotations

from app.models import TeamMessage, Teammate

# Kinds that carry conversation. Routing cards and "Picked it up." are noise.
SPOKEN_KINDS = {"user", "agent", "blocked"}
PICKED_UP = "Picked it up."

MAX_HISTORY = 10
MAX_LINE = 400


def transcript(history: list[TeamMessage], mates: list[Teammate]) -> list[str]:
    """Recent spoken rows, oldest first, one line each, as `Name: text`."""
    names = {m.id: m.display_name for m in mates}
    lines: list[str] = []
    for row in history:
        if row.kind not in SPOKEN_KINDS or row.text.strip() == PICKED_UP:
            continue
        who = "User" if row.kind == "user" else names.get(row.from_teammate_id, "Teammate")
        text = " ".join(row.text.split())
        if len(text) > MAX_LINE:
            text = text[: MAX_LINE - 1] + "…"
        lines.append(f"{who}: {text}")
    return lines[-MAX_HISTORY:]


def compose_prompt(
    *,
    mate: Teammate,
    mates: list[Teammate],
    history: list[TeamMessage],
    text: str,
    lead_id: int | None = None,
) -> str:
    """The user turn for a run started from the room. Plain text, no JSON."""
    others = [m for m in mates if m.id != mate.id]
    roster = ", ".join(
        f"{m.display_name} ({m.job_title}{', lead' if m.id == lead_id else ''})"
        for m in others
    ) or "nobody else"
    role = " (the lead)" if mate.id == lead_id else ""

    # The latest message is the one to answer; it is already the last row of
    # the history, so drop it there to avoid quoting it twice.
    earlier = [r for r in history if not (r.kind == "user" and r.text == text)]
    lines = transcript(earlier, mates)
    recent = "\n".join(lines) if lines else "(nothing yet)"

    return (
        f"You are {mate.display_name}, {mate.job_title}{role}, on a small team of "
        f"AI agents. You are replying in the team's group chat, which the whole team "
        f"and the person who owns it can read.\n"
        f"What you do: {mate.description or mate.job_title}.\n"
        f"Teammates: {roster}.\n"
        # Rendered by the executor with the other placeholders, so a reply that
        # mentions the time does not invent one.
        f"The current time (UTC) is {{{{now}}}}.\n\n"
        f"Recent conversation, oldest first:\n{recent}\n\n"
        f"The latest message, addressed to you:\n{text}\n\n"
        f"Reply as {mate.display_name}, in the first person, to the person who wrote "
        f"it. Be direct: lead with the answer, keep it under 120 words unless a list "
        f"is needed, and do not repeat the question back. Use your tools when the "
        f"answer needs live data; never invent data you did not fetch. If you cannot "
        f"do part of it, say exactly what is missing. Plain markdown is fine."
    )
