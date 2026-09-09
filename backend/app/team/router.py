"""What happens to one message in the room (plan FR-14), all visible in the thread.

1. ``@name``  -> straight to that teammate, the lead is skipped (the lead
                 itself can be mentioned; then it does the work, not the routing).
2. no lead    -> a ``no_lead`` row is written and nothing runs.
3. otherwise  -> the lead decides: hand it off (``handoff`` row + a run), take it
                 (``self``: the lead's own agent runs), or answer in the thread
                 (``reply``: an ``agent`` row and no run).

A teammate that is already busy does not drop the message: a ``queued`` row
holds it and it starts the moment the current run ends (see ``drain_queue``).
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import registry
from app.exceptions.errors import ConflictException
from app.models import Agent, AgentTool, Connection, Team, TeamMessage, Teammate
from app.runtime.runs import enqueue_run
from app.team import lead as lead_module
from app.team.context import compose_prompt

MENTION = re.compile(r"@([A-Za-z0-9_]+)")
PICKED_UP = "Picked it up."
HISTORY_ROWS = 24


async def roster(session: AsyncSession, team_id: int) -> list[Teammate]:
    result = await session.execute(select(Teammate).where(Teammate.team_id == team_id))
    return list(result.scalars().all())


async def recent(session: AsyncSession, team_id: int, limit: int = HISTORY_ROWS) -> list[TeamMessage]:
    """The newest rows, returned oldest first."""
    rows = (
        await session.execute(
            select(TeamMessage)
            .where(TeamMessage.team_id == team_id)
            .order_by(TeamMessage.at.desc(), TeamMessage.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))


def find_mention(text: str, mates: list[Teammate]) -> Teammate | None:
    match = MENTION.search(text)
    if not match:
        return None
    handle = match.group(1).lower()
    for mate in mates:
        if mate.display_name.lower() == handle:
            return mate
    for mate in mates:
        if mate.display_name.lower().startswith(handle):
            return mate
    return None


async def _blocked_reason(session: AsyncSession, mate: Teammate) -> str | None:
    """A teammate stops only when a connection *it actually uses* has expired.

    Scoped to this teammate's own tools on purpose: one expired account
    elsewhere in the workspace must not silently block the whole team.
    """
    agent = await session.get(Agent, mate.agent_id)
    if agent is None:
        return "its agent no longer exists"

    granted = (
        await session.execute(select(AgentTool).where(AgentTool.agent_id == agent.id))
    ).scalars().all()
    providers = {
        registry.provider_for(row.tool_name)
        for row in granted
        if not row.tool_name.startswith("mcp:")
    }
    providers.discard(None)
    if not providers:
        return None

    result = await session.execute(
        select(Connection).where(
            Connection.user_id == agent.user_id, Connection.provider.in_(providers)
        )
    )
    connections = result.scalars().all()
    expired = next((c for c in connections if c.status == "expired"), None)
    if expired is not None:
        return f"{expired.provider} access expired — reconnect it on the Connections screen"

    from app.config import settings

    if settings.CONNECTOR_STUBS:
        return None
    connected = {c.provider for c in connections if c.status == "connected"}
    missing = sorted(providers - connected)
    if missing:
        return f"{missing[0]} is not connected — connect it on the Connections screen"
    return None


async def _say(session: AsyncSession, team_id: int, **fields) -> TeamMessage:
    row = TeamMessage(team_id=team_id, **fields)
    session.add(row)
    await session.commit()
    return row


async def _start(session: AsyncSession, team: Team, mate: Teammate, text: str) -> TeamMessage | None:
    """Queue the teammate's agent; say why not (``blocked``) or hold it (``queued``)."""
    reason = await _blocked_reason(session, mate)
    if reason:
        await _say(session, team.id, kind="blocked", from_teammate_id=mate.id, text=f"{reason}.")
        return None

    mates = await roster(session, team.id)
    history = await recent(session, team.id)
    prompt = compose_prompt(
        mate=mate, mates=mates, history=history, text=text, lead_id=team.lead_teammate_id
    )

    agent = await session.get(Agent, mate.agent_id)
    try:
        run = await enqueue_run(session, agent, trigger="team", prompt_override=prompt)
    except ConflictException:
        # Busy, not lost: the row keeps the message and drain_queue starts it
        # when the current run ends.
        await _say(session, team.id, kind="queued", from_teammate_id=mate.id, text=text)
        return None

    return await _say(
        session, team.id, kind="agent", from_teammate_id=mate.id, text=PICKED_UP, run_id=run.id
    )


async def drain_queue(session: AsyncSession, mate: Teammate) -> TeamMessage | None:
    """Start the oldest message waiting for this teammate, if any.

    Called after the teammate's run has released the agent; the queued row is
    replaced by the usual "Picked it up." so the thread reads in order.
    """
    waiting = (
        await session.execute(
            select(TeamMessage)
            .where(
                TeamMessage.team_id == mate.team_id,
                TeamMessage.kind == "queued",
                TeamMessage.from_teammate_id == mate.id,
            )
            .order_by(TeamMessage.at, TeamMessage.id)
            .limit(1)
        )
    ).scalars().first()
    if waiting is None:
        return None

    team = await session.get(Team, mate.team_id)
    text = waiting.text
    await session.delete(waiting)
    await session.commit()
    return await _start(session, team, mate, text)


async def post_message(session: AsyncSession, team: Team, text: str) -> dict:
    """Handle one message to the room. Returns what the thread gained."""
    await _say(session, team.id, kind="user", text=text)

    mates = await roster(session, team.id)
    lead = next((m for m in mates if m.id == team.lead_teammate_id), None)

    # 1. A direct @mention skips the routing — the lead included.
    mentioned = find_mention(text, mates)
    if mentioned is not None:
        await _start(session, team, mentioned, text)
        return {"route": "direct", "teammate_id": mentioned.id}

    # 2. No lead: say so in the thread rather than dropping the message.
    if lead is None:
        await _say(
            session,
            team.id,
            kind="no_lead",
            text=(
                "Nobody claimed this. There is no lead on the team, so a message "
                "to the room has no owner."
            ),
        )
        return {"route": "no_lead", "teammate_id": None}

    # 3. The lead decides, with the recent thread in front of it.
    others = [m for m in mates if m.id != lead.id]
    history = await recent(session, team.id)
    decision = await lead_module.choose(text, others, lead=lead, history=history)

    if decision.action == "reply":
        await _say(
            session, team.id, kind="agent", from_teammate_id=lead.id, text=decision.reply
        )
        return {"route": "lead_reply", "teammate_id": lead.id}

    if decision.action == "self":
        await _start(session, team, lead, text)
        return {"route": "lead_self", "teammate_id": lead.id, "reason": decision.reason}

    await _say(
        session,
        team.id,
        kind="handoff",
        from_teammate_id=lead.id,
        to_teammate_id=decision.teammate_id,
        text=decision.reason,
    )
    target = next(m for m in others if m.id == decision.teammate_id)
    await _start(session, team, target, text)
    return {
        "route": "handoff",
        "teammate_id": decision.teammate_id,
        "reason": decision.reason,
    }
