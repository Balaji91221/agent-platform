import type { ReactNode } from 'react';
import { CardHead } from '../ui';

export type PartRow = { part: string; on: string; job: ReactNode };

export const COMPONENTS: PartRow[] = [
  {
    part: 'Web API',
    on: 'FastAPI',
    job: 'Everything the browser talks to — the form, the chat builder, and the team thread. All three produce the same agent record.',
  },
  {
    part: 'Scheduler',
    on: 'one process',
    job: (
      <>
        Decides <em>what</em> should run. Deliberately tiny, so it cannot get stuck behind slow work.
      </>
    ),
  },
  { part: 'Job queue', on: 'Redis', job: 'Decouples deciding from doing. A job sits here until a worker is free.' },
  { part: 'Workers', on: 'n processes', job: 'Do the slow work. This is the only part you scale.' },
  {
    part: 'Tool router',
    on: 'name lookup',
    job: 'Sends a tool call to the built-in adapter or the MCP client. The model sees one flat tool list either way.',
  },
  {
    part: 'Connector layer',
    on: 'per-app adapters',
    job: 'One file per app. Adding a connector should touch nothing else.',
  },
  {
    part: 'MCP client',
    on: 'HTTP + SSE',
    job: 'Handshakes with a registered server, caches its tool list, and calls it on demand. Tools arrive without anyone writing an adapter.',
  },
  {
    part: 'Notifier',
    on: 'email · Slack · webhook',
    job: 'Reports failures and expiring connections. Reads quiet hours before it sends anything.',
  },
  {
    part: 'Credential store',
    on: 'encrypted column',
    job: 'OAuth tokens, API keys, and MCP bearer tokens encrypted at rest, decrypted and refreshed just before use rather than on a timer.',
  },
  {
    part: 'Database',
    on: 'PostgreSQL',
    job: 'Agents, schedules, connections, registered MCP servers, teams and their threads, and every run with its logs.',
  },
];

export const DELEGATION: PartRow[] = [
  {
    part: 'Lead agent',
    on: 'you choose, 0 or 1',
    job: 'Default owner of every unaddressed message. Any teammate can be promoted or stood down; routes by job title and never calls a tool itself.',
  },
  {
    part: 'Specialist',
    on: 'n teammates',
    job: 'One narrow job each. Easier to trust and easier to fix than one agent that does everything.',
  },
  {
    part: 'Handoff card',
    on: 'thread event',
    job: 'Makes delegation visible. Without it you cannot tell why an agent got involved.',
  },
  {
    part: 'Shared context',
    on: 'the thread',
    job: 'Every teammate reads the same history, so context never has to be copied across.',
  },
  {
    part: 'Shared connections',
    on: 'account-wide',
    job: 'Authorised once, reachable by every teammate. Convenient, but the blast radius is the whole team.',
  },
  {
    part: 'Blocked state',
    on: 'per teammate',
    job: 'A teammate that cannot finish stops and names what it needs, rather than inventing an answer.',
  },
];

export function PartsTable({ title, rows }: { title: string; rows: PartRow[] }) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <CardHead title={title} />
      <table>
        <thead>
          <tr>
            <th>Part</th>
            <th>Built on</th>
            <th>Job</th>
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
