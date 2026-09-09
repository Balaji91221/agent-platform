"""Every setting the platform reads, in one place (plan NFR — no hardcoded values)."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Agent Platform"
    APP_VERSION: str = "2.0.0"
    # True prints tracebacks into 500 responses; keep it off unless debugging locally.
    DEBUG: bool = False

    # Postgres via docker-compose. Override with a sqlite+aiosqlite URL to run
    # with no Docker at all — every query works on both.
    DATABASE_URL: str = "postgresql+asyncpg://relay:relay@localhost:5432/relay"
    REDIS_URL: str = "redis://localhost:6379/0"

    # The frontend (Next.js) origin.
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3100",
        "http://localhost:3000",
    ]

    # Plan §0: the UI's "Free plan — 5 agents" number, made real.
    MAX_AGENTS_PER_USER: int = 5

    # Plan NFR-3 / NFR-8.
    RUN_TIMEOUT_SECONDS: int = 300
    MAX_TOOL_CALLS_PER_RUN: int = 20
    TOOL_CALL_TIMEOUT_SECONDS: int = 30
    RETRY_BACKOFF_SECONDS: list[float] = [1.0, 2.0, 4.0]
    MAX_ATTEMPTS: int = 3

    SCHEDULER_TICK_SECONDS: int = 30

    # "fake"      replays canned model turns — testable with no API key, no spend
    # "anthropic" calls the Anthropic API
    # "nvidia"    calls NVIDIA's OpenAI-compatible catalogue of open models
    MODEL_PROVIDER: str = "fake"
    ANTHROPIC_API_KEY: str = ""

    # NVIDIA NIM / build.nvidia.com — OpenAI-compatible chat completions.
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_STREAM: bool = True
    NVIDIA_MAX_TOKENS: int = 16384
    NVIDIA_TEMPERATURE: float = 1.0
    NVIDIA_SEED: int | None = 0
    # Reasoning models think for thousands of characters before every answer.
    # Off by default: measured 14s -> a few seconds per run. Set to True for
    # tasks where a slower, more careful answer is worth it.
    NVIDIA_THINKING: bool = False
    # Effort sent when thinking is on and the model advertises reasoning support.
    NVIDIA_REASONING_EFFORT: str = "max"

    # Plan §3: every UI model name maps to a real model id in one place, so a
    # rename or a new open model is a one-line change.
    MODEL_IDS: dict[str, str] = {
        # Anthropic
        "claude-sonnet-5": "claude-sonnet-5",
        "claude-opus-5": "claude-opus-5",
        "claude-haiku-4.5": "claude-haiku-4-5",
        # NVIDIA-hosted open models. The catalogue lists more, but many return
        # 404 "not found for account" on this key; only ones that answered a
        # real request are kept. Measured 2026-09-08, fastest first.
        "nemotron-3-super": "nvidia/nemotron-3-super-120b-a12b",
        "mistral-nemotron": "mistralai/mistral-nemotron",
        "gpt-oss-20b": "openai/gpt-oss-20b",
        "nemotron-lightning": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "kimi-k3": "moonshotai/kimi-k3",
        "deepseek-v4-pro": "deepseek-ai/deepseek-v4-pro-0813",
        "llama-3.2-90b-vision": "meta/llama-3.2-90b-vision-instruct",
    }

    # Which UI names belong to which provider, so the API can validate a choice
    # and the UI can group them.
    NVIDIA_MODELS: list[str] = [
        "nemotron-3-super",
        "mistral-nemotron",
        "gpt-oss-20b",
        "nemotron-lightning",
        "kimi-k3",
        "deepseek-v4-pro",
        "llama-3.2-90b-vision",
    ]

    # Models that accept reasoning_effort.
    NVIDIA_REASONING_MODELS: list[str] = ["kimi-k3", "deepseek-v4-pro"]

    # Models that accept image content.
    NVIDIA_VISION_MODELS: list[str] = ["llama-3.2-90b-vision"]

    # A structured answer is a few hundred tokens; more just slows the reply.
    NVIDIA_JSON_MAX_TOKENS: int = 700
    LEAD_MODEL: str = "nemotron-3-super"
    BUILDER_MODEL: str = "nemotron-3-super"
    # Asked at the same time as BUILDER_MODEL; the first usable answer wins.
    # On a shared endpoint the fastest model changes minute to minute, so
    # racing them turns "sum of timeouts" into "fastest of the three".
    BUILDER_FALLBACK_MODELS: list[str] = ["nemotron-lightning", "gpt-oss-20b"]
    # Overall cap for the race. A chat reply must land while the typing dots are up.
    BUILDER_TIMEOUT_SECONDS: int = 45

    # Plan NFR-2. Generated on first boot in dev; must be set explicitly in prod.
    CREDENTIAL_KEY: str = ""

    # Connectors call the real Gmail / Slack APIs. True only in tests: canned
    # answers, no network, and no connection required.
    CONNECTOR_STUBS: bool = False

    # OAuth clients. An unconfigured provider refuses to start sign-in (422) rather
    # than pretending; the token-paste path on the Connections screen still works.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    SLACK_CLIENT_ID: str = ""
    SLACK_CLIENT_SECRET: str = ""
    # Where the provider sends the browser back: {OAUTH_REDIRECT_BASE}/connections/oauth/{provider}/callback
    OAUTH_REDIRECT_BASE: str = "http://localhost:8000"
    # Full override when the URI registered in the Google console differs.
    GOOGLE_REDIRECT_URI: str = ""

    # "demo": X-User-Id header or the seeded demo user (tests, offline dev).
    # "google": every request needs the session cookie from Sign in with Google.
    AUTH_MODE: str = "demo"
    SESSION_COOKIE: str = "relay_session"
    SESSION_TTL_DAYS: int = 30
    # First Google login takes over the seeded demo user (its agents, team,
    # connections) instead of starting empty. Single-user dev instances only.
    CLAIM_DEMO_USER: bool = True

    # Where notifications go (email + Slack member lookup). Empty = the user's own email.
    NOTIFY_EMAIL: str = ""

    # Workspace-level key for the YouTube connector when no connection is pasted.
    YOUTUBE_API_KEY: str = ""
    # Where the callback sends the browser afterwards.
    FRONTEND_URL: str = "http://localhost:3100"

    # Plan NFR-11 — "console" prints instead of sending, so it is verifiable offline.
    # "smtp" sends through the server below; "gmail" sends through the user's own
    # Gmail connection (OAuth sign-in on the Connections screen).
    EMAIL_SENDER: str = "console"
    EMAIL_FROM: str = "relay@example.com"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_STARTTLS: bool = True

    # Only for tests / single-process runs: when Redis is unreachable, use
    # in-process queues instead of refusing to queue. With separate API and
    # worker processes a local queue is a black hole, so this is off by default.
    QUEUE_LOCAL_FALLBACK: bool = False

    # Queue names on Redis.
    JOB_QUEUE: str = "agent_platform:jobs"
    NOTIFY_QUEUE: str = "agent_platform:notifications"
    RUN_CHANNEL_PREFIX: str = "agent_platform:run:"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
