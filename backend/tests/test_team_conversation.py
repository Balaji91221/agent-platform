"""The room as a conversation: the lead answers or acts, nobody's message is dropped,
a teammate knows who it is and what was said, and a long thread still shows today."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import Agent, Run, Team, TeamMessage, Teammate
from app.team import lead as lead_module
from app.team.context import compose_prompt
from app.team.router import drain_queue, post_message


@pytest.fixture
async def client(session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _team(session, user) -> tuple[Team, list[Teammate]]:
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
            team_id=team.id, agent_id=agent.id, display_name=name, job_title=title,
            description=desc,
        )
        session.add(mate)
        await session.commit()
        await session.refresh(mate)
        mates.append(mate)
    team.lead_teammate_id = mates[0].id
    await session.commit()
    return team, mates


async def _rows(session, team_id: int) -> list[TeamMessage]:
    result = await session.execute(
        select(TeamMessage).where(TeamMessage.team_id == team_id).order_by(TeamMessage.id)
    )
    return list(result.scalars().all())


class _Scripted:
    """A provider whose routing answer is fixed by the test."""

    def __init__(self, answer: dict):
        self.answer = answer
        self.prompts: list[str] = []

    async def json_object(self, *, model, system, prompt, schema):
        self.prompts.append(prompt)
        return self.answer


# ---------------------------------------------------------------- the thread endpoint


async def test_thread_returns_the_newest_rows_oldest_first(client, session, user):
    team = Team(user_id=user.id)
    session.add(team)
    await session.commit()
    for i in range(5):
        session.add(TeamMessage(team_id=team.id, kind="user", text=f"m{i}"))
    await session.commit()

    r = await client.get("/team/messages?limit=2", headers={"X-User-Id": str(user.id)})
    assert r.status_code == 200
    assert [m["text"] for m in r.json()] == ["m3", "m4"], "the newest two, in reading order"


# ---------------------------------------------------------------- routing outcomes


async def test_mentioning_the_lead_goes_straight_to_the_lead(session, user, monkeypatch):
    team, mates = await _team(session, user)
    seen = {}

    async def fake_enqueue(session_, agent, trigger, prompt_override=None):
        seen["agent_id"], seen["prompt"] = agent.id, prompt_override
        run = Run(agent_id=agent.id, trigger=trigger, status="queued")
        session_.add(run)
        await session_.commit()
        await session_.refresh(run)
        return run

    monkeypatch.setattr("app.team.router.enqueue_run", fake_enqueue)
    result = await post_message(session, team, "@Ada what are you picking up today?")

    assert result["route"] == "direct" and result["teammate_id"] == mates[0].id
    assert seen["agent_id"] == mates[0].agent_id, "the lead's own agent runs it"
    assert "handoff" not in [r.kind for r in await _rows(session, team.id)]
    # The agent is told who it is and that it is the lead.
    assert "You are Ada, Chief of staff (the lead)" in seen["prompt"]


async def test_lead_takes_a_job_that_is_its_own(session, user, monkeypatch):
    team, mates = await _team(session, user)
    scripted = _Scripted({"action": "self", "teammate_id": 0, "reason": "Planning is mine.", "reply": ""})
    monkeypatch.setattr(lead_module, "get_provider", lambda *_: scripted)

    result = await post_message(session, team, "plan next week's priorities")

    assert result["route"] == "lead_self" and result["teammate_id"] == mates[0].id
    rows = await _rows(session, team.id)
    picked = [r for r in rows if r.kind == "agent" and r.run_id is not None]
    assert len(picked) == 1 and picked[0].from_teammate_id == mates[0].id
    assert "handoff" not in [r.kind for r in rows]


async def test_lead_answers_small_talk_in_the_thread_without_a_run(session, user, monkeypatch):
    team, mates = await _team(session, user)
    scripted = _Scripted(
        {"action": "reply", "teammate_id": 0, "reason": "", "reply": "Hi! Ask me anything."}
    )
    monkeypatch.setattr(lead_module, "get_provider", lambda *_: scripted)

    result = await post_message(session, team, "hi")

    assert result["route"] == "lead_reply"
    rows = await _rows(session, team.id)
    reply = rows[-1]
    assert reply.kind == "agent" and reply.from_teammate_id == mates[0].id
    assert reply.text == "Hi! Ask me anything." and reply.run_id is None
    assert (await session.execute(select(Run))).scalars().all() == [], "no run for small talk"
    # The lead saw the roster and its own identity.
    assert "You are Ada, Chief of staff" in scripted.prompts[0]
    assert "Ravi" in scripted.prompts[0]


async def test_lead_sees_the_recent_thread_when_deciding(session, user, monkeypatch):
    team, mates = await _team(session, user)
    session.add(TeamMessage(team_id=team.id, kind="user", text="earlier: the Acme invoice"))
    session.add(
        TeamMessage(team_id=team.id, kind="agent", from_teammate_id=mates[2].id, text="Paid on the 3rd.")
    )
    await session.commit()
    scripted = _Scripted({"action": "reply", "teammate_id": 0, "reason": "", "reply": "Yes."})
    monkeypatch.setattr(lead_module, "get_provider", lambda *_: scripted)

    await post_message(session, team, "was it paid?")

    prompt = scripted.prompts[0]
    assert "User: earlier: the Acme invoice" in prompt
    assert "Ravi: Paid on the 3rd." in prompt


async def test_nothing_matching_gets_a_who_does_what_reply_not_a_run(session, user):
    """Fake provider + no keyword hit: the deterministic backstop never starts a run."""
    team, mates = await _team(session, user)
    result = await post_message(session, team, "hello there")

    assert result["route"] == "lead_reply"
    text = (await _rows(session, team.id))[-1].text
    assert "Mira handles inbox and comms" in text and "Ravi handles billing analyst" in text
    assert (await session.execute(select(Run))).scalars().all() == []


async def test_a_wrong_id_from_the_model_falls_back_to_keywords(session, user, monkeypatch):
    team, mates = await _team(session, user)
    scripted = _Scripted({"action": "handoff", "teammate_id": 999, "reason": "x", "reply": ""})
    monkeypatch.setattr(lead_module, "get_provider", lambda *_: scripted)

    result = await post_message(session, team, "check the overdue invoices against the contract")
    assert result["route"] == "handoff" and result["teammate_id"] == mates[2].id


# ---------------------------------------------------------------- busy teammates


async def test_a_busy_teammate_queues_the_message_and_starts_it_after_the_run(session, user):
    team, mates = await _team(session, user)
    mira = mates[1]
    agent = await session.get(Agent, mira.agent_id)
    agent.is_running = True
    await session.commit()

    result = await post_message(session, team, "@Mira read the Acme thread")
    assert result["route"] == "direct"

    rows = await _rows(session, team.id)
    queued = [r for r in rows if r.kind == "queued"]
    assert len(queued) == 1 and queued[0].from_teammate_id == mira.id
    assert queued[0].text == "@Mira read the Acme thread", "the message is held, not dropped"
    assert "blocked" not in [r.kind for r in rows]

    # The run ends and the agent is released; the drain starts the held message.
    agent.is_running = False
    await session.commit()
    started = await drain_queue(session, mira)

    assert started is not None and started.run_id is not None
    rows = await _rows(session, team.id)
    assert [r for r in rows if r.kind == "queued"] == []
    assert rows[-1].kind == "agent" and rows[-1].text == "Picked it up."


async def test_drain_with_nothing_waiting_is_a_no_op(session, user):
    team, mates = await _team(session, user)
    assert await drain_queue(session, mates[1]) is None
    assert await _rows(session, team.id) == []


# ---------------------------------------------------------------- what the agent is told


def _mate(id_: int, name: str, title: str, desc: str = "") -> Teammate:
    return Teammate(id=id_, team_id=1, agent_id=id_, display_name=name, job_title=title, description=desc)


def test_team_prompt_carries_identity_roster_and_history():
    ada, mira = _mate(1, "Ada", "Chief of staff"), _mate(2, "Mira", "Inbox and comms", "Reads mail.")
    history = [
        TeamMessage(team_id=1, kind="user", text="Anything urgent?"),
        TeamMessage(team_id=1, kind="agent", from_teammate_id=2, text="Picked it up.", run_id=4),
        TeamMessage(team_id=1, kind="handoff", from_teammate_id=1, to_teammate_id=2, text="Mira reads mail."),
        TeamMessage(team_id=1, kind="agent", from_teammate_id=2, text="Two from Acme, one overdue."),
        TeamMessage(team_id=1, kind="user", text="@Mira which one is overdue?"),
    ]
    prompt = compose_prompt(
        mate=mira, mates=[ada, mira], history=history, text="@Mira which one is overdue?", lead_id=1
    )

    assert prompt.startswith("You are Mira, Inbox and comms, on a small team")
    assert "What you do: Reads mail." in prompt
    assert "Teammates: Ada (Chief of staff, lead)." in prompt
    assert "User: Anything urgent?" in prompt
    assert "Mira: Two from Acme, one overdue." in prompt
    assert "Picked it up." not in prompt, "routing noise stays out"
    assert "Mira reads mail." not in prompt, "handoff cards stay out"
    # The message being answered appears once, as the thing to answer.
    assert prompt.count("@Mira which one is overdue?") == 1
    assert "Reply as Mira, in the first person" in prompt
    assert "{{now}}" in prompt, "the executor fills the clock in, so the agent never guesses it"


def test_team_prompt_trims_long_history():
    mira = _mate(2, "Mira", "Inbox")
    history = [TeamMessage(team_id=1, kind="user", text=f"message {i}") for i in range(30)]
    prompt = compose_prompt(mate=mira, mates=[mira], history=history, text="now")
    assert "message 29" in prompt and "message 19" not in prompt, "only the last 10 lines"
