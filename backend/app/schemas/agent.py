from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ToolGrant(BaseModel):
    tool_name: str
    can_write: bool = False


class ScheduleIn(BaseModel):
    cron: str = "0 9 * * *"
    timezone: str = "Asia/Kolkata"
    is_paused: bool = False


class ScheduleOut(ScheduleIn):
    next_due_at: datetime | None = None
    words: str = ""
    next_runs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    system_prompt: str = ""
    user_prompt: str = ""
    model: str = "nemotron-3-super"
    tools: list[ToolGrant] = Field(default_factory=list)
    schedule: ScheduleIn | None = None


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    system_prompt: str | None = None
    user_prompt: str | None = None
    model: str | None = None
    tools: list[ToolGrant] | None = None
    schedule: ScheduleIn | None = None


class AgentOut(BaseModel):
    id: int
    name: str
    description: str
    system_prompt: str
    user_prompt: str
    model: str
    is_running: bool
    created_at: datetime
    tools: list[ToolGrant] = Field(default_factory=list)
    schedule: ScheduleOut | None = None

    model_config = ConfigDict(from_attributes=True)


class RunOut(BaseModel):
    id: int
    agent_id: int
    trigger: str
    status: str
    attempt: int
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    output: str | None = None
    error: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunLogOut(BaseModel):
    seq: int
    at: datetime
    kind: str
    line: str

    model_config = ConfigDict(from_attributes=True)


class JobRunOut(BaseModel):
    """One Jenkins build. `status` is the only field the UI switches on."""

    job: str
    # none | queued | running | success | failure | unavailable | disabled
    status: str
    build_number: int | None = None
    url: str | None = None
    message: str = ""


class A2AOut(BaseModel):
    """How another agent reaches this one. `token` is a bearer credential."""

    enabled: bool
    card_url: str
    endpoint_url: str
    token: str


class DeploymentOut(BaseModel):
    """Everything the agent detail screen shows about CI and A2A, in one call."""

    agent_id: int
    slug: str
    host_entry: str
    hosts_file: str
    enabled: bool
    jobs: list[JobRunOut] = Field(default_factory=list)
    a2a: A2AOut
