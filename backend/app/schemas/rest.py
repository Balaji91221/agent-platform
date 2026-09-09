"""Request/response shapes for connections, MCP, team, notifications, builder."""

from datetime import datetime

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------- connections


class ConnectionCreate(BaseModel):
    kind: str = Field(pattern="^(oauth|api_key|custom_http)$")
    provider: str
    label: str = ""
    secret: str | None = None
    base_url: str | None = None
    auth_header: str | None = None


class ConnectionOut(BaseModel):
    id: int
    kind: str
    provider: str
    label: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- mcp


class McpServerCreate(BaseModel):
    url: str
    auth_kind: str = Field(default="none", pattern="^(oauth|bearer|none)$")
    token: str | None = None
    name: str = ""

    @field_validator("url")
    @classmethod
    def _must_be_http(cls, value: str) -> str:
        value = value.strip()
        if not re.match(r"^https?://[^\s/]+", value):
            raise ValueError("must be an http(s) URL")
        return value


class McpServerOut(BaseModel):
    id: int
    name: str
    url: str
    auth_kind: str
    status: str
    tools_json: list = Field(default_factory=list)
    last_handshake_at: datetime | None = None
    error: str | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- team


class TeammateCreate(BaseModel):
    agent_id: int
    display_name: str = Field(min_length=1, max_length=120)
    job_title: str = Field(min_length=1, max_length=200)
    description: str = ""
    colour: str = "#1a73e8"
    make_lead: bool = False


class TeammateUpdate(BaseModel):
    display_name: str | None = None
    job_title: str | None = None
    description: str | None = None
    colour: str | None = None


class TeammateOut(BaseModel):
    id: int
    agent_id: int
    display_name: str
    job_title: str
    description: str
    colour: str
    is_lead: bool = False
    is_running: bool = False
    agent_name: str = ""

    model_config = ConfigDict(from_attributes=True)


class TeamOut(BaseModel):
    id: int
    lead_teammate_id: int | None
    teammates: list[TeammateOut] = Field(default_factory=list)


class LeadSet(BaseModel):
    teammate_id: int | None = None


class TeamMessageIn(BaseModel):
    text: str = Field(min_length=1)


class TeamMessageOut(BaseModel):
    id: int
    kind: str
    from_teammate_id: int | None
    to_teammate_id: int | None
    text: str
    run_id: int | None
    at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- notifications


class NotificationOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    run_id: int | None
    # Resolved through the run, so the feed can link straight to the agent's log.
    agent_id: int | None = None
    agent_name: str = ""
    is_read: bool
    at: datetime

    model_config = ConfigDict(from_attributes=True)


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class PrefsIn(BaseModel):
    email_on: bool = True
    slack_dm_on: bool = False
    webhook_on: bool = False
    webhook_url: str | None = None
    quiet_from: str | None = None
    quiet_to: str | None = None
    notify_on_success: bool = False

    @field_validator("quiet_from", "quiet_to")
    @classmethod
    def _valid_clock(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not _HHMM.match(value):
            raise ValueError("must be HH:MM, 24-hour")
        return value

    @field_validator("webhook_url")
    @classmethod
    def _valid_webhook(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not re.match(r"^https?://", value):
            raise ValueError("must be an http(s) URL")
        return value


class PrefsOut(BaseModel):
    """Deliberately not a PrefsIn: what is already stored must always be readable,
    even a value written before a validator existed."""

    email_on: bool
    slack_dm_on: bool
    webhook_on: bool
    webhook_url: str | None
    quiet_from: str | None
    quiet_to: str | None
    notify_on_success: bool
    # Read-only: the address email actually goes to (NOTIFY_EMAIL, else the user's own).
    email_to: str = ""

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- builder


class DraftTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(max_length=4000)


class DraftIn(BaseModel):
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("say something first")
        return value.strip()
    # The browser's zone; the draft's schedule defaults to it.
    timezone: str | None = None
    # Prior turns, oldest first, so "and post it to Slack" can follow "summarise my mail".
    history: list[DraftTurn] = Field(default_factory=list, max_length=20)


# ---------------------------------------------------------------- stats


class StatsOut(BaseModel):
    # The sidebar's plan box: how many agents exist against the plan cap.
    agents_used: int = 0
    agent_limit: int = 0
    runs_today: int
    runs_total: int
    success_rate: float
    median_duration_seconds: float | None
    failures_this_week: int
    runs_per_hour: list[dict]
    outcomes: dict
    busiest_agents: list[dict]


class MeOut(BaseModel):
    id: int
    email: str
    name: str | None = None
    picture: str | None = None

    model_config = ConfigDict(from_attributes=True)
