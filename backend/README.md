# Relay backend

The backend for the agent platform: agents, schedules, connectors, MCP servers,
teams with a lead, notifications, and a chat builder.

- **Flow, diagrams, and the screen → endpoint map:** [`docs/FLOW.md`](docs/FLOW.md)
- **The plan this implements:** `PLAN-new-agent-platform-v2.md`

## Run it

```bash
python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env
docker compose up -d          # Postgres :5432 + Redis :6379
./.venv/bin/alembic upgrade head
./scripts/dev.sh              # API :8000 + scheduler + worker + notifier
```

Open <http://localhost:8000/docs>.

No Docker? Set `DATABASE_URL=sqlite+aiosqlite:///./agent_platform.db` and the
whole stack runs on SQLite with in-process queues. The test suite passes on
both.

## Processes

| Command | Job |
|---|---|
| `uvicorn app.main:app` | The HTTP API |
| `python -m app.scheduler.ticker` | Wakes every 30s, queues what is due |
| `python -m app.runtime.worker` | Runs agents. The only thing you scale |
| `python -m app.notify.dispatcher` | Sends email / Slack DM / webhook |

## Model providers

| `MODEL_PROVIDER` | Calls | Needs |
|---|---|---|
| `fake` | canned turns — every path testable, no spend | nothing |
| `anthropic` | the Anthropic API | `ANTHROPIC_API_KEY` |
| `nvidia` | NVIDIA-hosted open models | `NVIDIA_API_KEY` |

**Defaults are NVIDIA.** A new agent, the chat builder, and the team lead all use
`nemotron-3-super` (120B, ~3–7 s per run with thinking off). An agent whose
`model` is one of the NVIDIA names routes to NVIDIA whatever `MODEL_PROVIDER`
says, so one workspace can run Claude and open models side by side.

| Setting | Default | What it does |
|---|---|---|
| `BUILDER_MODEL` / `LEAD_MODEL` | `nemotron-3-super` | chat builder and team lead |
| `BUILDER_FALLBACK_MODELS` | `["nemotron-lightning","gpt-oss-20b"]` | raced with the builder model; first good JSON wins |
| `BUILDER_TIMEOUT_SECONDS` | `45` | overall cap on the race |
| `NVIDIA_THINKING` | `false` | `true` re-enables reasoning (slower, better on hard prompts) |
| `NVIDIA_JSON_MAX_TOKENS` | `700` | budget for the builder's JSON answer |

Open models available (`app/config.py` → `MODEL_IDS`, verified against
`GET /v1/models`): `nemotron-3-super`, `nemotron-lightning`, `mistral-nemotron`,
`gpt-oss-20b`, `kimi-k3`, `deepseek-v4-pro`, `llama-3.2-90b-vision`.

NVIDIA speaks the OpenAI wire format, so `app/runtime/nvidia_provider.py`
translates three things — tools into the `function` envelope, tool calls off the
message rather than a content block, and tool results as `role: "tool"`. The
executor never sees the difference.

## Sign in

`AUTH_MODE=google` (set in `.env`) puts the site behind Sign in with Google:
`GET /auth/google/start` → Google → `/auth/google/callback` sets a signed,
httpOnly session cookie (30 days); `/auth/me` returns the user; `POST /auth/logout`
clears it. Every other endpoint answers 401 without the cookie and the frontend
goes to `/login`. The first Google login claims the seeded demo workspace
(`CLAIM_DEMO_USER=true`) so existing agents are kept. `AUTH_MODE=demo` keeps the
header/seeded-user behaviour for tests and offline work. The same consent also asks for Gmail and Sheets; every granted Google connector
is created at sign-in (`GOOGLE_CONNECTOR_SCOPES` in `security/oauth.py`), with a
refresh token, so no separate Connect step is needed. Register
`http://localhost:8000/auth/google/callback` in the Google console.

## Connections

Gmail and Slack call the real APIs (`app/connectors/gmail.py`, `slack.py`) with
the user's token. A tool whose provider is not connected returns
`Blocked: gmail is not connected — connect it on the Connections screen` to the
model; it never returns sample data. `CONNECTOR_STUBS=true` (tests only) swaps in
canned answers.

Two ways to connect:

| Way | Needs | How |
|---|---|---|
| Paste a token | nothing | Connections screen → Connect → paste a Slack bot token / Google access token |
| Sign in (OAuth) | `GOOGLE_CLIENT_ID`+`SECRET` or `SLACK_CLIENT_ID`+`SECRET` | `GET /connections/oauth/{provider}/start` → browser → `/callback` stores access+refresh token, refreshed 5 min before expiry |

OAuth redirect URI to register with the provider:
`{OAUTH_REDIRECT_BASE}/connections/oauth/{provider}/callback` (default
`http://localhost:8000/...`). The callback bounces to `{FRONTEND_URL}/connections`.

Notifications: `EMAIL_SENDER=console` (default) logs the mail; `smtp` sends it
through `SMTP_HOST/PORT/USER/PASSWORD`; `gmail` sends through the user's own Gmail
connection (OAuth sign-in, no SMTP). `NOTIFY_EMAIL` routes every notification to
one inbox. Slack DMs go through the user's own Slack connection. Webhooks POST
the event JSON.

YouTube (`youtube.video_info`, `youtube.search`) reads with a pasted API key or,
failing that, `YOUTUBE_API_KEY` from `.env`.

`GET /health` reports `db` and `redis` and returns 503 when the database is down.

## Notifications

`GET /notifications` rows carry `agent_id` and `agent_name` (resolved through the
run), so the UI can open the exact run behind a failure; `POST /notifications/{id}/read`
clears one row. `GET /notifications/prefs` includes a read-only `email_to`: where email
really goes (`NOTIFY_EMAIL`, else the signed-in user's address).

## Team room

`POST /team/messages` is one conversation, not a job form:

- `@Name …` goes straight to that teammate, the lead included.
- Otherwise the lead reads the message with up to 10 recent lines of the thread and does
  one of three things: hands it off (a `handoff` card says why), takes it itself, or
  answers in the thread with no run at all (greetings, "who does what", things nobody
  here can do).
- A busy teammate does not drop a message: a `queued` row holds it and it starts the
  moment the current run ends.
- The teammate's agent is told who it is, who else is on the team, and what was said
  recently (`app/team/context.py`), so its reply reads as part of the conversation.
  The answer lands in the thread before the agent's lock is released, so the page
  never stops polling before the reply exists.
- `GET /team/messages?limit=N` returns the newest N rows, oldest first.

## Tests

```bash
./.venv/bin/python -m pytest -q                    # against DATABASE_URL
DATABASE_URL="sqlite+aiosqlite:///./t.db" ./.venv/bin/python -m pytest -q
```

194 tests. They pass on Postgres and SQLite alike. Provider calls are asserted
through `httpx.MockTransport` (`tests/test_connectors_live.py`); nothing in the
suite touches the network.

## Layout

```
app/
├── api/           HTTP endpoints, one file per area
├── models/        the 14 tables
├── schemas/       request and response shapes
├── runtime/       executor, tool router, worker, run lifecycle, logging
├── scheduler/     cron maths and the 30-second ticker
├── team/          the lead's decision and the three routing cases
├── connectors/    one file per built-in app
├── mcp/           MCP client and tool-list cache
├── notify/        the notifier process and its three channels
├── builder/       plain words → a draft agent
└── security/      encryption, OAuth refresh, ownership
```
