# Flow — how the frontend and the backend act together

Two separate programs, one HTTP boundary.

| | Frontend | Backend |
|---|---|---|
| Runs on | `localhost:3100` (Next.js) | `localhost:8000` (FastAPI) |
| Owns | screens, forms, the thread as you type it | agents, runs, credentials, schedules |
| Started by | `npm run dev` | `./scripts/dev.sh` |
| Processes | 1 | 4 — API, scheduler, worker, notifier |

The frontend never calls Gmail, Slack, or a model. It calls the backend; the backend
holds every credential and makes every outside call.

---

## 1. The shape of the whole system

```mermaid
flowchart TD
    UI["Next.js UI<br/>localhost:3100"] -->|"HTTP + JSON"| API["FastAPI<br/>localhost:8000"]
    PEER["Outside A2A agent"] -->|"card + SendMessage<br/>bearer token"| API
    API -->|"create · deploy · delete"| CI["Jenkins<br/>localhost:8090"]
    CI -->|"host entry"| HOSTS[("jenkins/hosts")]
    API --> DB[("Database<br/>agents · runs · team<br/>credentials · MCP servers")]
    API -->|"Run now"| Q["Redis job queue"]
    API -->|"team message"| LEAD["Team router<br/>lead picks a teammate"]
    LEAD -->|"delegates"| Q
    TICK["Scheduler<br/>wakes every 30s"] -->|"reads what is due"| DB
    TICK -->|"agent is due"| Q
    Q --> W["Worker"]
    W --> EX["Executor<br/>the agent loop"]
    EX -->|"prompt"| MODEL["Model API<br/>Anthropic · NVIDIA open models"]
    EX --> ROUTE["Tool router"]
    ROUTE -->|"built-in name"| CONN["Connector layer"]
    ROUTE -->|"mcp: name"| MCP["MCP client"]
    CONN --> CRED[("Credential store<br/>decrypt just before use")]
    MCP --> CRED
    CONN --> APPS["Slack · Gmail · your API"]
    MCP --> SERVERS["MCP servers"]
    EX -->|"one line per step"| DB
    EX -->|"live"| SSE["SSE stream"]
    SSE --> UI
    W -->|"outcome"| NOTE["Notifier<br/>email · Slack DM · webhook"]
```

Two optional edges, both **off by default**: Jenkins (`JENKINS_ENABLED`) provisions a
host entry per agent, and A2A (`A2A_ENABLED`) lets an outside agent call one of ours.
Neither is on the path of a normal run, and neither being down stops an agent from
being created, run, or deleted.

**Why four processes, not one.** The scheduler only decides *what* is due, so it can
never get stuck. The workers do the slow part and are the only thing you scale. The
notifier talks to a mail provider that may be slow, and that must never hold up a run.

---

## 2. Three ways a run starts

All three end at the same place: a job on the queue, with the agent already flagged
as running so nothing can queue it twice.

### 2a. The user presses "Run now"

```mermaid
sequenceDiagram
    participant U as Browser (/detail)
    participant A as FastAPI
    participant D as Database
    participant Q as Job queue
    participant W as Worker

    U->>A: POST /agents/1/run
    A->>D: is_running False→True (atomic)
    alt already running
        A-->>U: 409 Conflict
    else claimed
        A->>D: INSERT run (status=queued)
        A->>Q: push {run_id}
        A-->>U: 202 + run id
        U->>A: GET /runs/{id}/stream
        W->>Q: pop job
        W->>D: status=running
        loop until done, or 20 calls, or 5 min
            W->>W: model call → tool call
            W->>D: INSERT run_log
            W-->>U: SSE line (under 2s)
        end
        W->>D: status=succeeded
        W-->>U: SSE {event: done}
    end
```

### 2b. The schedule fires, with nobody watching

```mermaid
sequenceDiagram
    participant T as Scheduler
    participant D as Database
    participant Q as Job queue
    participant W as Worker
    participant N as Notifier

    loop every 30 seconds
        T->>D: which agents were due before now and are not running?
        D-->>T: agent 1 (next_due_at passed)
        T->>D: claim + INSERT run (trigger=schedule)
        T->>Q: push {run_id}
        T->>D: next_due_at = next cron time
    end
    W->>Q: pop job
    W->>W: run the agent loop
    alt failed
        W->>W: retry 1s, then 2s, then 4s
        W->>N: queue a failure notification
        N->>N: quiet hours? failures still pass
        N-->>N: email / Slack DM / webhook
    end
```

### 2c. A message to the team

```mermaid
sequenceDiagram
    participant U as Browser (/team)
    participant A as FastAPI
    participant L as Lead agent
    participant Q as Job queue

    U->>A: POST /team/messages {"text": "..."}
    alt mentions @name (the lead included)
        A->>Q: queue that teammate's agent, or hold a queued row if it is busy
        A-->>U: {route: "direct"}
    else no lead set
        A->>A: write a no_lead row, run nothing
        A-->>U: {route: "no_lead"}
    else
        A->>L: one model call — message, job titles, up to 10 recent lines of the thread
        L-->>A: {action: handoff | self | reply, teammate_id, reason, reply}
        alt handoff
            A->>A: write the handoff row (the receipt)
            A->>Q: queue the chosen teammate's agent
            A-->>U: {route: "handoff", teammate_id, reason}
        else self
            A->>Q: queue the lead's own agent
            A-->>U: {route: "lead_self"}
        else reply
            A->>A: write the lead's answer as an agent row, no run
            A-->>U: {route: "lead_reply"}
        end
    end
```

The lead gets **no tools**, so a wrong pick costs one cheap run and can never cause a
side effect. The id it returns is checked against the roster before anything runs, and
when the model is down or names nobody real, a keyword backstop routes work and
otherwise answers with who does what — it never starts a run on a guess.

When the run finishes, the worker writes the teammate's answer into the thread
*before* releasing the agent's lock, then starts the oldest `queued` message waiting
for that teammate, if any. The agent's user turn (`app/team/context.py`) carries its
name and job title, the roster, and the recent transcript, so the reply reads as part
of the conversation.

### 2d. Another agent calls through A2A

This is the one path that does **not** go through the queue. The caller is blocking
on the answer, so the run happens inside the API process; a queued job would also be
picked up by a worker and run twice.

```mermaid
sequenceDiagram
    participant P as Outside agent
    participant A as FastAPI /a2a
    participant D as Database
    participant X as Executor (in-process)

    P->>A: GET /a2a/agents/1/.well-known/agent-card.json
    alt A2A_ENABLED false, agent has A2A off, or no such agent
        A-->>P: 404
    else
        A->>D: agent row + tool grants
        A-->>P: card — skills, bearer scheme, text-only
    end

    P->>A: POST /a2a/agents/1 {SendMessage} + Bearer token
    alt token missing or wrong
        A-->>P: HTTP 401 · error -32000
    else no text in parts
        A-->>P: error -32602
    else
        A->>D: is_running False→True (atomic)
        alt already running
            A-->>P: error -32004 "already running"
        else claimed
            A->>D: INSERT run (trigger=a2a)
            A->>X: perform_run(prompt = message text)
            loop up to 3 attempts · 1s / 2s / 4s
                X->>D: INSERT run_log · publish to SSE channel
            end
            X->>D: status, output, ended_at · release lock
            X->>X: advance schedule · team reply · notify
            A-->>P: result.task — COMPLETED + artifact, or FAILED + message
        end
    end
```

The request is held for the whole run: up to `RUN_TIMEOUT_SECONDS` (300 s) per
attempt. Anything in front of the backend needs a read timeout above that.

### 2e. Jenkins: create is fire-and-forget, deploy waits for a number

```mermaid
sequenceDiagram
    participant U as Browser
    participant A as FastAPI
    participant D as Database
    participant J as Jenkins

    U->>A: POST /agents
    A->>D: INSERT agent, tools, schedule
    alt JENKINS_ENABLED false
        A->>A: status = disabled, Jenkins never contacted
    else
        A->>J: GET crumb · POST agent-create/buildWithParameters
        alt Jenkins down or refused
            A->>A: log WARNING, status = unavailable / failure
        else accepted
            J-->>A: 201 + queue item URL
        end
    end
    A-->>U: 201 agent (never waits for the build)

    U->>A: POST /agents/1/deploy
    A->>J: POST agent-deploy/buildWithParameters
    J-->>A: 201 + queue item URL
    loop up to 20 × 0.5 s
        A->>J: GET queue/item/N/api/json
        J-->>A: executable? {number, url}
    end
    A-->>U: 200 {jobs: [{status: running, build_number, url}]}

    loop every 4 s while any job is queued or running
        U->>A: GET /agents/1/deployment
        A->>J: GET job/*/api/json?tree=builds[…parameters]
        A-->>U: latest build per job whose AGENT_ID = 1
    end
```

Builds are matched to an agent by the `AGENT_ID` build parameter, not by a stored
build number, so nothing has to be kept in step with Jenkins' own history.

---

## 3. Which screen calls which endpoint

The frontend routes already exist; these are the calls to wire into each.

| Frontend route | Calls | Purpose |
|---|---|---|
| `/today` | `GET /stats?range=today\|7d\|30d` | Every tile, chart, and ring |
| `/agents` | `GET /agents` · `DELETE /agents/{id}` | The table |
| `/create` | `GET /connections/tools` · `POST /agents` | Tool list, then save (402 past the cap) |
| `/agents/[id]` | `GET /agents/{id}` · `GET /agents/{id}/runs` · `GET /runs/{id}/logs` · `GET /runs/{id}/stream` · `POST /agents/{id}/run` · `POST /agents/{id}/pause\|resume` · `GET /agents/{id}/deployment` · `POST /agents/{id}/deploy` | Detail, history, live log, Run now, pause, Jenkins jobs + host entry, A2A card + token |
| `/chat` | `POST /builder/draft` | Plain words → a draft the form opens |
| `/team` | `GET /team` · `GET /team/messages` · `POST /team/messages` · `PUT /team/lead` | Roster, thread, lead |
| `/mate` | `GET /agents` · `POST /team/teammates` | Pick an agent, name it |
| `/connections` | `GET/POST/DELETE /connections` · `GET/POST /mcp-servers` | Apps and MCP servers |
| `/notifications` | `GET /notifications` · `POST /notifications/read-all` · `GET/PUT /notifications/prefs` | Feed, quiet hours |

`/architecture` reads `GET /health` for the run caps it prints, so the numbers on that page
come from the backend rather than being typed into the UI.

---

## 4. Where the limits live

| Limit | Value | Enforced in |
|---|---|---|
| Scheduler tick | 30s | `scheduler/ticker.py` |
| Scheduled run starts within | 60s of due | tick interval |
| Run wall clock | 5 min | `runtime/executor.py` |
| Tool calls per run | 20 | `runtime/executor.py` |
| One tool call | 30s, then cancelled | `runtime/router.py` |
| Retries | 3 · 1s / 2s / 4s | `runtime/runs.py` |
| Log line reaches the browser | under 2s | `runtime/logger.py` → SSE |
| Agents per user | 5 → HTTP 402 | `api/agents.py` |
| Same agent twice at once | refused → HTTP 409 | `runtime/runs.py` |
| A2A `SendMessage` held open | up to 300s per attempt | `a2a/server.py` → `RUN_TIMEOUT_SECONDS` |
| A2A call to a busy agent | refused → JSON-RPC `-32004` | `a2a/server.py` |
| One Jenkins HTTP call | 10s | `JENKINS_TIMEOUT_SECONDS` |
| Deploy waits for a build number | 20 × 0.5s = 10s, then `queued` | `cicd/jenkins.py` |
| Deployment card refresh | every 4s while a build is in flight | `components/agents/deployment-card.tsx` |

---

## 5. Two rules that hold everywhere

**Credentials.** Encrypted before they are written, decrypted in memory only in the
moment before a tool call. Four kinds share one store: OAuth tokens, API keys, custom
HTTP headers, and MCP bearer tokens.

**Ownership.** Every query for a user-owned row goes through `security/ownership.py`,
which adds `WHERE user_id = me`. Another user's id returns 404, never 403, so ids
cannot be probed. This is a database rule, not something the UI hides.

---

## 6. Running it

```bash
# backend — API, scheduler, worker, notifier
cd backend && ./scripts/dev.sh          # → localhost:8000/docs

# frontend
npm run dev                             # → localhost:3100
```

Every default model is `nemotron-3-super` on NVIDIA (`NVIDIA_API_KEY`), with
thinking off (`NVIDIA_THINKING=false`) so a run lands in 3–7 s. `MODEL_PROVIDER=fake`
replays canned turns for tests; `anthropic` (+ `ANTHROPIC_API_KEY`) for Claude. An
agent whose `model` is an NVIDIA name routes there whatever the provider setting.

Tools are real: Gmail and Slack call their APIs with the user's token. Nothing is
connected until the user connects it — paste a token on the Connections screen, or
set `GOOGLE_CLIENT_ID/SECRET` or `SLACK_CLIENT_ID/SECRET` and use Sign in. A run
that needs a missing connection gets `Blocked: … is not connected` as its tool
result and says so; a team message to such a teammate writes a `blocked` row.

Postgres and Redis come from `docker compose up -d`; set a
`sqlite+aiosqlite://` URL to run with no Docker at all.

Jenkins (`docker compose up -d jenkins`, port 8090) and A2A are both **off** until
`JENKINS_ENABLED=true` / `A2A_ENABLED=true` are set. Off means: every Jenkins job
reports `disabled`, and every `/a2a/...` route is 404. Both are documented in full in
the README.
