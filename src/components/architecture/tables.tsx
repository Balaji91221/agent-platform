import type { ReactNode } from 'react';
import { CardHead } from '../ui';

export type PartRow = { part: string; on: string; where: string; job: ReactNode };

export const COMPONENTS: PartRow[] = [
  {
    part: 'Web API',
    on: 'FastAPI',
    where: 'app/api/',
    job: 'The only thing the browser talks to. The form, the chat builder, and the team thread all end at the same agent record.',
  },
  {
    part: 'Scheduler',
    on: 'one process',
    where: 'app/scheduler/ticker.py',
    job: (
      <>
        Decides <em>what</em> is due, never runs it. It claims the agent before queueing, so two ticks cannot queue the
        same one.
      </>
    ),
  },
  {
    part: 'Job queue',
    on: 'Redis list',
    where: 'app/runtime/bus.py',
    job: 'Separates deciding from doing. A job waits here until a worker is free, and falls back to an in-process queue when Redis is absent.',
  },
  {
    part: 'Workers',
    on: 'n processes',
    where: 'app/runtime/worker.py',
    job: 'Do the slow part: the model calls, the tool calls, the retries. This is the only piece you add more of.',
  },
  {
    part: 'Agent loop',
    on: 'per run',
    where: 'app/runtime/executor.py',
    job: (
      <>
        Sends the prompts and the allowed tools, then acts on the reply until the model is done or a cap is hit. It fills
        in <span className="mono">{'{{now}}'}</span>, <span className="mono">{'{{last_run}}'}</span> and{' '}
        <span className="mono">{'{{agent_name}}'}</span> first, so an agent never guesses the date.
      </>
    ),
  },
  {
    part: 'Tool router',
    on: 'name lookup',
    where: 'app/runtime/router.py',
    job: 'Sends a call to a built-in connector or to the MCP client, and loads and decrypts the credential it needs. An expired connection raises instead of calling unauthenticated.',
  },
  {
    part: 'Connectors',
    on: 'per-app adapters',
    where: 'app/connectors/',
    job: 'Gmail, Slack, Sheets, YouTube, and plain HTTP. One file each, so adding an app touches nothing else.',
  },
  {
    part: 'MCP client',
    on: 'HTTP + SSE',
    where: 'app/mcp/client.py',
    job: 'Handshakes with a server you registered, caches its tool list, and calls it on demand. Those tools arrive without anyone writing an adapter.',
  },
  {
    part: 'Notifier',
    on: 'email · Slack · webhook',
    where: 'app/notify/dispatcher.py',
    job: 'Runs apart so a slow mail provider can never hold up a run. Failures always go out; successes only if you asked for them.',
  },
  {
    part: 'Recovery sweep',
    on: 'on startup',
    where: 'app/runtime/recovery.py',
    job: 'Clears locks a killed process left behind, so an agent cannot be stuck as running forever.',
  },
  {
    part: 'Credential store',
    on: 'encrypted column',
    where: 'app/security/crypto.py',
    job: 'OAuth tokens, API keys, custom headers, and MCP bearer tokens. Encrypted at rest, decrypted in the moment before a call, never on a timer.',
  },
  {
    part: 'Ownership guard',
    on: 'every query',
    where: 'app/security/ownership.py',
    job: 'Adds the user filter in the database layer. Someone else’s id returns 404, not 403, so ids cannot be probed.',
  },
  {
    part: 'A2A endpoint',
    on: 'per agent, off by default',
    where: 'app/a2a/',
    job: 'Publishes every agent to the Agent2Agent protocol (v1.0): a public card at /a2a/agents/{id}/.well-known/agent-card.json and a JSON-RPC SendMessage that runs the agent and returns a task. Guarded by a per-agent bearer token; 404 while A2A_ENABLED is false.',
  },
  {
    part: 'Jenkins client',
    on: 'three jobs, off by default',
    where: 'app/cicd/jenkins.py',
    job: 'Fires agent-create, agent-deploy and agent-delete, each writing one host entry. Jenkins being down is an ordinary status on the Deployment card, never a reason an agent cannot be created or deleted.',
  },
];

export const DELEGATION: PartRow[] = [
  {
    part: 'Lead',
    on: 'you pick, 0 or 1',
    where: 'app/team/lead.py',
    job: 'Owns anything you did not address. The routing call itself has no tools, so a wrong pick costs one cheap call and can never touch your accounts.',
  },
  {
    part: 'Three actions',
    on: 'handoff · self · reply',
    where: 'app/team/lead.py',
    job: 'Hand it to a teammate, run its own agent, or just answer in the thread. Small talk gets an answer without a run.',
  },
  {
    part: 'Direct mention',
    on: 'skips the lead',
    where: 'app/team/router.py',
    job: (
      <>
        An <span className="mono">@name</span> goes straight to that teammate, the lead included. Exact name first, then
        a unique prefix.
      </>
    ),
  },
  {
    part: 'Handoff card',
    on: 'thread row',
    where: 'app/team/router.py',
    job: 'Says who passed the work, who got it, and why. Without it you cannot tell why a second agent joined in.',
  },
  {
    part: 'Shared transcript',
    on: 'up to 10 lines',
    where: 'app/team/context.py',
    job: 'A teammate is handed its own name and job title, the roster, the clock, and the recent thread, so its reply reads as part of the conversation.',
  },
  {
    part: 'Queued message',
    on: 'busy teammate',
    where: 'app/team/router.py',
    job: 'A message to an agent that is mid-run is held as a row and started the moment that run ends. Nothing is dropped and nothing runs twice.',
  },
  {
    part: 'Blocked reply',
    on: 'missing connection',
    where: 'app/team/router.py',
    job: 'A teammate that cannot finish names what it needs and stops, rather than inventing the answer.',
  },
  {
    part: 'No lead',
    on: 'allowed',
    where: 'app/team/router.py',
    job: 'With nobody leading, an unaddressed message is left unclaimed on purpose and the thread says so.',
  },
];

export function PartsTable({ title, blurb, rows }: { title: string; blurb?: string; rows: PartRow[] }) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <CardHead title={title} blurb={blurb} />
      <table>
        <thead>
          <tr>
            <th>Part</th>
            <th>Built on</th>
            <th>Job</th>
            <th>In the code</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.part}>
              <td>
                <b style={{ fontWeight: 500 }}>{r.part}</b>
              </td>
              <td>
                <span className="mono" style={{ color: 'var(--ink-3)' }}>
                  {r.on}
                </span>
              </td>
              <td style={{ color: 'var(--ink-2)' }}>{r.job}</td>
              <td>
                <span className="mono" style={{ color: 'var(--ink-3)', whiteSpace: 'nowrap' }}>
                  {r.where}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
