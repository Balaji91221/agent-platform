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

---

## 3. Which screen calls which endpoint

The frontend routes already exist; these are the calls to wire into each.

| Frontend route | Calls | Purpose |
|---|---|---|
| `/today` | `GET /stats?range=today\|7d\|30d` | Every tile, chart, and ring |
| `/agents` | `GET /agents` · `DELETE /agents/{id}` | The table |
| `/create` | `GET /connections/tools` · `POST /agents` | Tool list, then save (402 past the cap) |
| `/detail` | `GET /agents/{id}` · `GET /agents/{id}/runs` · `GET /runs/{id}/logs` · `GET /runs/{id}/stream` · `POST /agents/{id}/run` | Detail, history, live log, Run now |
| `/chat` | `POST /builder/draft` | Plain words → a draft the form opens |
| `/team` | `GET /team` · `GET /team/messages` · `POST /team/messages` · `PUT /team/lead` | Roster, thread, lead |
| `/mate` | `GET /agents` · `POST /team/teammates` | Pick an agent, name it |
| `/connections` | `GET/POST/DELETE /connections` · `GET/POST /mcp-servers` | Apps and MCP servers |
| `/notifications` | `GET /notifications` · `POST /notifications/read-all` · `GET/PUT /notifications/prefs` | Feed, quiet hours |

`/detail` is currently hard-coded to one agent; it becomes `/agents/[id]` when wired.

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
