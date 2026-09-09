"""Team routing, cron maths, and the chat builder."""

from datetime import datetime, timezone

import pytest

from app.models import Agent, Team, TeamMessage, Teammate
from app.scheduler.cron import next_due, preview, validate_cron
from app.team.router import find_mention, post_message


async def _team_with_roster(session, user) -> tuple[Team, list[Teammate]]:
    team = Team(user_id=user.id, lead_teammate_id=None)
    session.add(team)
    await session.commit()
    await session.refresh(team)

    mates = []
    for name, title, desc in [
        ("Ada", "Chief of staff", "Decides who should do it."),
        ("Mira", "Inbox and comms", "Reads mail and posts to Slack."),
        ("Ravi", "Billing analyst", "Checks invoices against the contract."),
    ]:
        agent = Agent(user_id=user.id, name=f"{name} agent", model="claude-sonnet-5")
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        mate = Teammate(
            team_id=team.id, agent_id=agent.id, display_name=name,
            job_title=title, description=desc,
        )
        session.add(mate)
        await session.commit()
        await session.refresh(mate)
        mates.append(mate)

    team.lead_teammate_id = mates[0].id
    await session.commit()
    return team, mates


async def _thread(session, team_id: int) -> list[TeamMessage]:
    rows = await session.execute(
        TeamMessage.__table__.select().where(TeamMessage.team_id == team_id)
    )
    return list(rows.fetchall())


async def test_lead_hands_billing_work_to_the_billing_analyst(session, user):
    """FR-14 case 3."""
    team, mates = await _team_with_roster(session, user)
    result = await post_message(session, team, "check the overdue invoices against the contract")

    assert result["route"] == "handoff"
    assert result["teammate_id"] == mates[2].id, "should pick Ravi, not Mira"

    kinds = [r.kind for r in await _thread(session, team.id)]
    assert "handoff" in kinds, "the handoff must be visible in the thread"


async def test_mention_goes_direct_and_writes_no_handoff(session, user):
    """FR-14 case 1 — the lead is skipped."""
    team, mates = await _team_with_roster(session, user)
    result = await post_message(session, team, "@Mira read the Acme thread")

    assert result["route"] == "direct"
    assert result["teammate_id"] == mates[1].id
    assert "handoff" not in [r.kind for r in await _thread(session, team.id)]


async def test_no_lead_records_the_event_and_runs_nothing(session, user):
    """FR-14 case 2 — nothing is silently dropped."""
    team, _ = await _team_with_roster(session, user)
    team.lead_teammate_id = None
    await session.commit()

    result = await post_message(session, team, "someone deal with the renewal")
    assert result["route"] == "no_lead"
    assert "no_lead" in [r.kind for r in await _thread(session, team.id)]


def test_find_mention_matches_by_name():
    mates = [
        Teammate(id=1, team_id=1, agent_id=1, display_name="Mira", job_title="t"),
        Teammate(id=2, team_id=1, agent_id=2, display_name="Ravi", job_title="t"),
    ]
    assert find_mention("@ravi look at this", mates).id == 2
    assert find_mention("no mention here", mates) is None


def test_cron_respects_the_users_timezone():
    """FR-2 — 9am means 9am where the user is."""
    ist = next_due("0 9 * * *", "Asia/Kolkata")
    utc = next_due("0 9 * * *", "UTC")
    assert ist.hour == 3 and ist.minute == 30, "09:00 IST is 03:30 UTC"
    assert utc.hour == 9 and utc.minute == 0
    assert ist.tzinfo == timezone.utc


def test_invalid_cron_is_rejected():
    from app.exceptions.errors import ValidationException

    with pytest.raises(ValidationException):
        validate_cron("not a cron")


def test_preview_returns_three_future_runs():
    rows = preview("0 9 * * 1-5", "Asia/Kolkata")
    assert len(rows) == 3


async def test_builder_returns_a_valid_draft():
    """FR-19 — plain words in, a schema-valid draft out."""
    from app.builder.draft import build

    result = await build("summarise my unread email every morning and post it to slack")
    assert result.kind == "draft"
    draft = result.draft
    assert draft.name
    validate_cron(draft.cron)
    from app.config import settings
    assert draft.model in settings.MODEL_IDS


async def test_builder_falls_back_when_the_model_misbehaves():
    """A malformed answer must not become an error screen."""
    from app.builder.draft import build

    class Broken:
        async def json_object(self, **kwargs):
            raise ValueError("not json")

    result = await build("watch for overdue invoices", provider=Broken())
    assert result.kind == "draft"
    assert result.draft.name == "watch for overdue invoices"[:40]
    validate_cron(result.draft.cron)


@pytest.mark.parametrize("text", ["hi", "hello there", "tell me claude", "what can you do?", "ok"])
async def test_builder_replies_instead_of_drafting_small_talk(text):
    """'hi' must never become an agent called 'hi'."""
    from app.builder.draft import build

    result = await build(text)
    assert result.kind == "reply"
    assert "agent" in result.text.lower()


@pytest.mark.parametrize(
    "text",
    ["summarise my inbox each morning", "watch for overdue invoices", "post standup reminders to slack daily"],
)
async def test_builder_drafts_real_tasks(text):
    from app.builder.draft import build

    assert (await build(text)).kind == "draft"


async def test_expired_connection_blocks_only_the_teammate_that_uses_it(session, user):
    """An expired account elsewhere must not block a teammate that never touches it."""
    from app.models import AgentTool, Connection

    team, mates = await _team_with_roster(session, user)
    ravi = mates[2]

    # Ravi reads Gmail; nobody uses Sheets.
    session.add(AgentTool(agent_id=ravi.agent_id, tool_name="gmail.list_unread"))
    session.add(
        Connection(user_id=user.id, kind="oauth", provider="sheets", status="expired")
    )
    await session.commit()

    result = await post_message(session, team, "check the overdue invoices")
    assert result["route"] == "handoff" and result["teammate_id"] == ravi.id
    assert "blocked" not in [r.kind for r in await _thread(session, team.id)]


async def test_expired_connection_does_block_the_teammate_that_uses_it(session, user):
    from app.models import AgentTool, Connection

    team, mates = await _team_with_roster(session, user)
    ravi = mates[2]

    session.add(AgentTool(agent_id=ravi.agent_id, tool_name="gmail.list_unread"))
    session.add(
        Connection(user_id=user.id, kind="oauth", provider="gmail", status="expired")
    )
    await session.commit()

    await post_message(session, team, "check the overdue invoices")
    kinds = [r.kind for r in await _thread(session, team.id)]
    assert "blocked" in kinds, "the teammate must stop and say what it needs"


async def test_a_team_run_replies_into_the_thread(session, user):
    """The teammate's output must reach the room, not just the run record."""
    from app.models import Run
    from app.runtime.runs import _post_team_reply
    from app.models import Agent

    team, mates = await _team_with_roster(session, user)
    ravi = mates[2]
    agent = await session.get(Agent, ravi.agent_id)

    run = Run(
        agent_id=agent.id, trigger="team", status="succeeded",
        output="Three invoices, one 14 days late.",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    await _post_team_reply(session, agent, run)

    rows = await _thread(session, team.id)
    replies = [r for r in rows if r.kind == "agent" and r.run_id == run.id]
    assert len(replies) == 1
    assert "14 days late" in replies[0].text


async def test_a_failed_team_run_says_so_in_the_thread(session, user):
    from app.models import Agent, Run
    from app.runtime.runs import _post_team_reply

    team, mates = await _team_with_roster(session, user)
    ravi = mates[2]
    agent = await session.get(Agent, ravi.agent_id)

    run = Run(agent_id=agent.id, trigger="team", status="failed", error="Stripe timed out")
    session.add(run)
    await session.commit()
    await session.refresh(run)

    await _post_team_reply(session, agent, run)

    blocked = [r for r in await _thread(session, team.id) if r.kind == "blocked"]
    assert blocked and "Stripe timed out" in blocked[0].text


async def test_a_scheduled_run_does_not_touch_the_thread(session, user):
    from app.models import Agent, Run
    from app.runtime.runs import _post_team_reply

    team, mates = await _team_with_roster(session, user)
    agent = await session.get(Agent, mates[2].agent_id)

    run = Run(agent_id=agent.id, trigger="schedule", status="succeeded", output="done")
    session.add(run)
    await session.commit()
    await session.refresh(run)

    before = len(await _thread(session, team.id))
    await _post_team_reply(session, agent, run)
    assert len(await _thread(session, team.id)) == before


async def test_builder_drops_tools_that_do_not_exist():
    """A model that invents a tool name must not produce a draft that fails on Create."""
    from app.builder.draft import build

    class Inventive:
        async def json_object(self, **kwargs):
            return {
                "intent": "draft", "reply": "", "name": "Digest", "description": "d",
                "system_prompt": "s", "user_prompt": "u", "model": "claude-sonnet-5",
                "cron": "0 8 * * *", "timezone": "UTC",
                "tools": ["fetch_unread_emails", "gmail.list_unread", "post_message_to_slack"],
            }

    result = await build("summarise my inbox", provider=Inventive())
    assert result.kind == "draft"
    assert result.draft.tools == ["gmail.list_unread"]


def test_builder_prompt_lists_the_real_tools():
    from app.builder.draft import DRAFT_SCHEMA, SYSTEM

    assert "gmail.list_unread" in SYSTEM
    assert "gmail.send" in DRAFT_SCHEMA["properties"]["tools"]["items"]["enum"]


async def test_builder_replies_honestly_when_the_model_is_down_on_small_talk():
    """Provider failure on 'hi' must not become an agent called 'hi'."""
    from app.builder.draft import build

    class Down:
        async def json_object(self, **kwargs):
            raise RuntimeError("upstream unreachable")

    result = await build("hi", provider=Down())
    assert result.kind == "reply"
    assert "couldn't reach" in result.text


async def test_builder_still_drafts_a_task_when_the_model_is_down():
    from app.builder.draft import build

    class Down:
        async def json_object(self, **kwargs):
            raise RuntimeError("upstream unreachable")

    result = await build("summarise my inbox each morning", provider=Down())
    assert result.kind == "draft" and result.draft.name.startswith("summarise")


async def test_builder_gives_up_at_its_timeout(monkeypatch):
    import asyncio
    from app.builder.draft import build
    from app.config import settings

    monkeypatch.setattr(settings, "BUILDER_TIMEOUT_SECONDS", 0.05)

    class Slow:
        async def json_object(self, **kwargs):
            await asyncio.sleep(1)
            return {}

    result = await build("hi", provider=Slow())
    assert result.kind == "reply" and "couldn't reach" in result.text


async def test_builder_falls_through_to_the_next_model(monkeypatch):
    """A dead primary must not block the answer from another model."""
    from app.builder import draft as mod

    calls = []

    class Dead:
        async def json_object(self, *, model, **kw):
            calls.append(model); raise RuntimeError("503")

    class Alive:
        async def json_object(self, *, model, **kw):
            calls.append(model)
            return {"intent": "reply", "reply": "Hello from the fallback", "name": "", "description": "",
                    "system_prompt": "", "user_prompt": "", "model": "claude-sonnet-5",
                    "cron": "0 9 * * *", "timezone": "UTC", "tools": []}

    providers = {"primary": Dead(), "backup": Alive()}
    monkeypatch.setattr(mod, "get_provider", lambda m: providers[m])

    result = await mod.build("hi", models=["primary", "backup"])
    assert result.kind == "reply" and "fallback" in result.text
    assert set(calls) == {"primary", "backup"}


async def test_builder_race_returns_the_fastest_and_cancels_the_rest(monkeypatch):
    import asyncio
    from app.builder import draft as mod

    finished = []

    def make(name, delay):
        class P:
            async def json_object(self, **kw):
                await asyncio.sleep(delay)
                finished.append(name)
                return {"intent": "reply", "reply": f"from {name}", "name": "", "description": "",
                        "system_prompt": "", "user_prompt": "", "model": "claude-sonnet-5",
                        "cron": "0 9 * * *", "timezone": "UTC", "tools": []}
        return P()

    providers = {"slow": make("slow", 0.5), "fast": make("fast", 0.02)}
    monkeypatch.setattr(mod, "get_provider", lambda m: providers[m])

    result = await mod.build("hi", models=["slow", "fast"])
    assert result.kind == "reply" and result.text == "from fast"
    await asyncio.sleep(0.6)
    assert finished == ["fast"], "the slow one must have been cancelled, not left running"


def test_default_models_are_ones_this_key_can_call():
    from app.config import settings

    for name in [settings.BUILDER_MODEL, *settings.BUILDER_FALLBACK_MODELS, settings.LEAD_MODEL]:
        assert name in settings.MODEL_IDS
