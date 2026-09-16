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

## Jenkins CI

Every agent has a lifecycle in Jenkins: it is provisioned when created, can be
redeployed on demand, and is torn down when deleted. Three parameterised jobs
carry that lifecycle. They are defined once, as Job DSL inside
`jenkins/casc.yaml` (Jenkins Configuration as Code), so the whole CI setup is
committed and a `docker compose down -v` loses nothing.

```bash
docker compose up -d jenkins     # http://localhost:8090 — user relay / relay
```

### The three jobs

| Job | Triggered by | Waits for a build number | Effect |
|---|---|---|---|
| `agent-create` | `POST /agents` | no | Appends `<ip>\t<slug>.<domain>` to the hosts file |
| `agent-deploy` | `POST /agents/{id}/deploy` | yes | Re-asserts the host entry, then runs the deploy step |
| `agent-delete` | `DELETE /agents/{id}` | no | Removes the host entry |

Every job receives the same six parameters: `AGENT_ID`, `AGENT_SLUG`,
`AGENT_NAME`, `HOST_IP`, `HOST_DOMAIN`, `HOSTS_FILE`. `AGENT_ID` is the one
the backend later reads back to find an agent's builds, so there is no table of
build numbers to keep in step with Jenkins' own history.

The deploy step is deliberately a placeholder. A Relay agent is a database row
that the worker executes; there is no image to push or process to restart. The
`agent-deploy` shell step is the hook where a real deployment would go.

### Endpoints

```
POST /agents/{id}/deploy       run agent-deploy, return once it has a build number
GET  /agents/{id}/deployment   host entry + latest build of each job + A2A details
```

Both are owner-scoped: another user's agent id answers 404. The agent detail
screen's Deployment card reads `GET /agents/{id}/deployment` every 4 s while
any build is `queued` or `running`, and stops on its own once nothing is.

`GET /agents/{id}/deployment` returns:

```json
{
  "agent_id": 1,
  "slug": "daily-digest-1",
  "host_entry": "127.0.0.1\tdaily-digest-1.relay.local",
  "hosts_file": "/opt/relay/hosts",
  "enabled": true,
  "jobs": [
    {"job": "agent-create", "status": "success", "build_number": 12,
     "url": "http://localhost:8090/job/agent-create/12/", "message": ""},
    {"job": "agent-deploy", "status": "none", "build_number": null,
     "url": null, "message": "Never run"},
    {"job": "agent-delete", "status": "none", "build_number": null,
     "url": null, "message": "Never run"}
  ],
  "a2a": {"enabled": false, "card_url": "...", "endpoint_url": "...", "token": "..."}
}
```

### Build status

`status` is the only field the UI switches on.

| Status | Meaning | Where it comes from |
|---|---|---|
| `none` | The job has never run for this agent | no build carries this `AGENT_ID` |
| `queued` | Jenkins accepted the request; no executor yet | `trigger()` with `wait=False`, or the queue wait timed out |
| `running` | A build is in progress | Jenkins reports `building: true` |
| `success` | Last build passed | Jenkins `result: SUCCESS` |
| `failure` | Last build failed, or Jenkins refused the trigger | any other `result`, or a non-2xx on trigger |
| `unavailable` | Jenkins cannot be reached, or the job is missing | connection error, or a non-200 on the job |
| `disabled` | `JENKINS_ENABLED` is false | never contacts Jenkins |

### Timing

| Step | Bound | Set by |
|---|---|---|
| Any single Jenkins HTTP call | 10 s | `JENKINS_TIMEOUT_SECONDS` |
| Create and delete, added to the API call | ~0.3 s (fire and forget) | `trigger(wait=False)` |
| Deploy, wait for a build number | up to 10 s (20 polls × 0.5 s) | `_queued_build` |
| Deployment card refresh | every 4 s while a build is in flight | `deployment-card.tsx` |

Create and delete do not wait for a build number. Measured on a local
Jenkins, waiting cost 6.4 s against 0.3 s without, and a user saving an agent
should not pay for CI. Deploy does wait, because the build number is the thing
the button was pressed for.

### Failure policy

`JENKINS_ENABLED` is **false** by default. When it is on and Jenkins is down,
absent, or refuses a build, the outcome is recorded as a job status and logged
at `WARNING`; it is never raised into the request. Concretely:

- `POST /agents` still returns 201 and the agent exists.
- `DELETE /agents/{id}` still returns 204.
- `POST /agents/{id}/deploy` returns 200 with `status: "unavailable"`.

The delete job is fired *before* the rows are removed, because the job needs
the agent's name to rebuild the slug. Jenkins POSTs carry a CSRF crumb fetched
on the same HTTP session; installs with crumbs off work unchanged.

### Host entries

The slug is `<name>-<id>`: lowercase, non-alphanumerics folded to `-`, cut to
40 characters, and always suffixed with the id. Two agents named "Daily
Digest" become `daily-digest-7` and `daily-digest-8`, so entries never collide.
A name with nothing usable in it (`"!!!"`) becomes `agent-<id>`.

Each job is idempotent. Re-running create never duplicates a line, deploy adds
the line only if it is missing, and delete on an absent entry succeeds. Delete
matches the whole label, so removing `api.relay.local` cannot touch
`internal-api.relay.local`.

Entries are written to `jenkins/hosts`, bind-mounted into the container at
`/opt/relay/hosts`. A container's own `/etc/hosts` is Docker-managed and
regenerated on restart, so it is not a durable place for them. To edit a real
machine's file, run the job with `HOSTS_FILE=/etc/hosts` on a Jenkins agent
that can write it. The delete job filters into a temp file and `cat`s back,
because `sed -i` cannot create its temp file next to a read-only bind mount.

### Configuration

| Setting | Default | Effect |
|---|---|---|
| `JENKINS_ENABLED` | `false` | Master switch. Off means every job reports `disabled` |
| `JENKINS_URL` | `http://localhost:8090` | Base URL the backend calls |
| `JENKINS_USER` / `JENKINS_PASSWORD` | `relay` / `relay` | Basic auth; the same values seed the CasC admin user |
| `JENKINS_TIMEOUT_SECONDS` | `10` | Per-request HTTP timeout |
| `JENKINS_CREATE_JOB` / `_DEPLOY_JOB` / `_DELETE_JOB` | `agent-create` / `agent-deploy` / `agent-delete` | Job names, if you rename them in `casc.yaml` |
| `AGENT_HOST_IP` | `127.0.0.1` | Address every host entry points at |
| `AGENT_HOST_DOMAIN` | `relay.local` | Suffix of every host entry |
| `AGENT_HOSTS_FILE` | `/opt/relay/hosts` | File the jobs edit, as seen from inside Jenkins |

The Jenkins image (`jenkins/Dockerfile`) is `jenkins/jenkins:lts-jdk21` with
`configuration-as-code`, `job-dsl` and `workflow-aggregator` baked in, the
setup wizard disabled, and `curl` installed so a job can smoke-test an agent.
Jenkins listens on `8090` on the host because `8080` and `8081` are commonly
taken by other local stacks.

## A2A (Agent2Agent)

Any agent can be an A2A agent. A2A is the open protocol for one agent to
discover another and hand it work; this backend implements the **v1.0**
specification's card plus synchronous `SendMessage` subset. An outside agent
reads the card to learn what an agent does and which tools it holds, then
sends a message and receives the run's output as a terminal task.

Exposure is two switches, both off by default:

| Switch | Where | Scope |
|---|---|---|
| `A2A_ENABLED` | backend `.env` | the whole server |
| `a2a_enabled` | per agent, "Agent-to-agent" card on the create/edit form | that one agent |

An agent is published only when both are on. `GET /agents/{id}/deployment`
returns `a2a.enabled` (the effective answer) plus `server_enabled` and
`agent_enabled` so the Deployment card can say which one is off.

### Endpoints

```
GET  /a2a/agents/{id}/.well-known/agent-card.json   discovery — public, no token
POST /a2a/agents/{id}                               JSON-RPC 2.0 — bearer token
```

The router is deliberately outside cookie auth: the caller is another agent,
not a browser. The card is public and carries the agent's name, description,
tool names, and its `user_prompt` as the example on the `run` skill, so treat
the prompt as visible to anyone who can reach the URL once `A2A_ENABLED` is
on. The RPC endpoint is guarded by the agent's own bearer token.

### The card

Nothing is published on create. The card is derived from the agent row on
every request, so it is live the moment `POST /agents` returns, reflects a
rename immediately, and is 404 after a delete. There is no registry to keep in
step.

| Card field | Value |
|---|---|
| `name`, `description` | The agent's own |
| `supportedInterfaces[0]` | `{url: <A2A_PUBLIC_URL>/a2a/agents/{id}, protocolBinding: "JSONRPC", protocolVersion: "1.0"}` |
| `provider` | `{organization: APP_NAME, url: A2A_PUBLIC_URL}` |
| `version` | `APP_VERSION` |
| `capabilities` | `streaming`, `pushNotifications`, `extendedAgentCard` all `false` |
| `securitySchemes` | one HTTP bearer scheme named `agentToken` |
| `defaultInputModes` / `defaultOutputModes` | `["text/plain"]` |
| `skills` | one `run` skill for the agent, plus one `tool:<name>` skill per granted tool |

Tools become skills so a caller choosing between agents can see, for example,
that one of them writes to Gmail. Each tool skill's description says `read
only` or `read and write`, taken from the grant.

### Sending a message

```bash
TOKEN=$(curl -s localhost:8000/agents/1/deployment | jq -r .a2a.token)
curl -s -X POST localhost:8000/a2a/agents/1 \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":
       {"role":"ROLE_USER","messageId":"m-1","parts":[{"text":"Summarise today"}]}}}'
```

What happens, in order:

1. `A2A_ENABLED`, the agent id, and the agent's own `a2a_enabled` are checked;
   any of them failing is a 404.
2. The bearer token is verified in constant time.
3. The text parts of the message are joined into the prompt. File and data
   parts are dropped: the card declares text only.
4. The agent is claimed with the same atomic `is_running` lock the scheduler
   and the Run button use. A busy agent is refused, not queued.
5. A `Run` row is created with `trigger=a2a` and executed **in-process**, with
   the normal retry policy (3 attempts, 1 s / 2 s / 4 s). It is not put on the
   queue, because a worker would then also pick it up and run it twice.
6. Every log line is written to `run_logs` and published on the run's stream
   channel, so the run appears in history and in the live log like any other.
7. The run's after-effects fire as usual: the schedule advances, a team reply
   is posted if the agent is a teammate, and a failure notification is sent.
8. The answer is returned as a terminal `Task`.

A successful run:

```json
{"jsonrpc": "2.0", "id": 1, "result": {"task": {
  "id": "run-42",
  "contextId": "…",
  "status": {"state": "TASK_STATE_COMPLETED", "timestamp": "2026-09-16T09:30:00Z"},
  "artifacts": [{"artifactId": "…", "name": "output", "parts": [{"text": "…"}]}],
  "history": [{"role": "ROLE_USER", "messageId": "…", "parts": [{"text": "Summarise today"}]}]
}}}
```

A failed run answers `TASK_STATE_FAILED` with the error text in
`status.message` and an empty `artifacts` list. `task.id` is `run-<id>`, so a
caller can find the run in `GET /agents/{id}/runs`. `contextId` echoes the
caller's, or a fresh UUID when none was given.

**The call blocks.** `SendMessage` is blocking by default in v1.0, so the HTTP
request is held for the length of the run, up to `RUN_TIMEOUT_SECONDS`
(default 300 s) per attempt. Callers, and any reverse proxy in front of the
backend, need a read timeout above that.

### Error codes

Errors ride inside the JSON-RPC envelope. The HTTP status is 200 in every
case but authentication.

| HTTP | Code | When |
|---|---|---|
| 401 | `-32000` | Missing, malformed, or wrong bearer token |
| 200 | `-32700` | Body is not valid JSON |
| 200 | `-32600` | Body is not an object, or `jsonrpc` is not `"2.0"` |
| 200 | `-32601` | Any method other than `SendMessage` |
| 200 | `-32602` | No `params.message`, or no text in its parts |
| 200 | `-32004` | The agent is already running |
| 200 | `-32603` | The run raised an unhandled exception |

`-32000` is used for a failed credential because the spec defines no code for
it: it says "HTTP 401, or a JSON-RPC custom error". The response carries both,
so a client that only reads the body and one that only reads the status each
see the refusal. `-32000` is the one code in JSON-RPC's implementation-defined
range that A2A's `-32001..-32099` has not claimed. It is not `-32600`, which
the spec reserves for a malformed Request object; a well-formed call with no
credential is not malformed.

### Authentication

Each agent has one bearer token: HMAC-SHA256 of its id, keyed by a hash of
`CREDENTIAL_KEY` with an `|a2a` suffix. The token is derived, not stored, so
there is no migration and no secret at rest, and the suffix keeps it from ever
colliding with a session signature derived from the same key.

The token is shown on the agent detail page behind a Show toggle and is
returned by `GET /agents/{id}/deployment` to the agent's owner. Verification is
a constant-time compare, so a wrong token leaks nothing through timing. One
agent's token does not open another.

Rotating `CREDENTIAL_KEY` revokes every token at once. That is the only
revocation a derived token has; per-agent rotation would need a stored secret.

### Discovery

The card lives at `/a2a/agents/{id}/.well-known/agent-card.json`, not at the
domain root, because one backend serves many agents. That is the spec's
"Direct Configuration" mechanism and is conformant, but a client that only
probes `{domain}/.well-known/agent-card.json` will find nothing. The spec's
answer for many agents behind one endpoint is the `AgentInterface.tenant`
field; per-agent URLs make it unnecessary here, so it is not set.
`A2A_PUBLIC_URL` must be the absolute origin outside callers use, because the
card's interface URLs are required to be absolute.

### Conformance

The card and the `SendMessage` task were verified against the spec's own
generated JSON Schema and parsed by the official `a2a-sdk` protobuf types.
Two defects that verification caught, both fixed:

- A naive `.isoformat()` timestamp the SDK refused. A2A timestamps are
  protobuf `Timestamp`, so RFC 3339 UTC with a trailing `Z`; SQLite hands back
  naive datetimes, and `_rfc3339` normalises them.
- The `-32600` authentication code discussed above.

### Configuration

| Setting | Default | Effect |
|---|---|---|
| `A2A_ENABLED` | `false` | Server switch. Off means every A2A route is 404 |
| `a2a_enabled` (per agent) | `false` | Agent switch, set on the form or by `PATCH /agents/{id}`. Off means that agent's routes are 404 |
| `A2A_PUBLIC_URL` | `http://localhost:8000` | Absolute origin written into the card's interface URL |
| `A2A_PROTOCOL_VERSION` | `1.0` | Value of `protocolVersion` on the card |
| `CREDENTIAL_KEY` | dev fallback | Root of every agent token; rotate to revoke all |
| `RUN_TIMEOUT_SECONDS` | `300` | Upper bound on how long a `SendMessage` is held, per attempt |

`A2A_ENABLED` is off by default because turning it on exposes agents, and the
tools they hold, to anything with the token. While off, every A2A route
answers 404 rather than 403: the spec forbids revealing that a resource the
caller cannot reach exists.

### Not implemented

Streaming, push notifications, `GetTask`, `CancelTask`, task history beyond the
echoed request, and the extended card. The card declares each capability
`false`, and any method other than `SendMessage` answers `-32601`.

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

212 tests. They pass on Postgres and SQLite alike. Provider calls are asserted
through `httpx.MockTransport` (`tests/test_connectors_live.py`); nothing in the
suite touches the network.

## Layout

```
app/
├── api/           HTTP endpoints, one file per area
├── a2a/           agent card, token, JSON-RPC SendMessage
├── cicd/          Jenkins client: trigger a job, read an agent's builds
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
