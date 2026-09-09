import { Fragment } from 'react';
import type { ReactNode } from 'react';
import { SystemDiagram } from '@/components/architecture/diagram';
import { DownloadDiagramButton } from '@/components/architecture/download-button';
import { COMPONENTS, DELEGATION, PartsTable } from '@/components/architecture/tables';
import { CardHead, PageHead } from '@/components/ui';

const FLOW: { title: string; blurb: ReactNode }[] = [
  {
    title: 'The user saves an agent',
    blurb:
      'Built in the form or drafted in chat — both land at the same web API, which writes the agent to PostgreSQL and works out when it is next due.',
  },
  {
    title: 'Something asks for a run',
    blurb:
      'Either the scheduler finds the agent due, or a message in the team thread is handed to it. Both paths end the same way: a job on the queue.',
  },
  {
    title: 'The scheduler wakes every 30 seconds',
    blurb: 'It asks one question: which agents were due before now and are not already running?',
  },
  {
    title: 'Or the lead agent delegates',
    blurb:
      "Whichever teammate you made lead reads the others' job titles, picks the closest match, and posts a handoff card. It queues the job but never calls a tool itself.",
  },
  {
    title: 'A worker picks the job up',
    blurb:
      'Workers are separate processes. Add more of them and more agents run at once; the scheduler never needs to scale.',
  },
  {
    title: 'The agent loop starts',
    blurb:
      'The worker sends the prompts and the allowed tool list to the model the agent was configured with, which replies with either an answer or a tool to call.',
  },
  {
    title: 'The tool router decides who handles the call',
    blurb: (
      <>
        A built-in name like <span className="mono">gmail.list_unread</span> goes to that app&rsquo;s adapter. Anything
        discovered from an MCP server goes to the MCP client instead. The model does not know the difference.
      </>
    ),
  },
  {
    title: 'The caller fetches a credential',
    blurb:
      "It pulls that user's token or API key, decrypts it, refreshes it if expired, then makes the real call. Nothing is refreshed on a timer.",
  },
  {
    title: 'The result goes back to the model',
    blurb: 'Steps six to eight repeat until the model is done, or the 20-call or 5-minute cap is hit.',
  },
  {
    title: 'Everything is written down',
    blurb:
      'Each step lands in the run record as it happens. The worker then computes the next due time and, if the outcome is worth hearing about, hands it to the notifier.',
  },
];

const LIMITS: [string, string][] = [
  ['Scheduler tick', 'every 30s'],
  ['Run timeout', '5 minutes'],
  ['Single tool call', '30s, then cancel'],
  ['Tool calls per run', '20'],
  ['Retries', '3 · 1s / 2s / 4s'],
  ['Overlapping runs', 'skipped'],
  ['Alerts in quiet hours', 'failures only'],
];

const HANDOFF: ReactNode[] = [
  'Your message lands in the group chat. There is one thread for the team, not one per agent.',
  <>
    If you typed an <span className="mono">@name</span>, it goes straight there and the lead is skipped.
  </>,
  <>
    Otherwise the teammate you marked as <b style={{ fontWeight: 500, color: 'var(--ink)' }}>lead</b> picks it up. The
    lead owns anything unaddressed, so no request sits unclaimed. A team with no lead leaves the message unclaimed on
    purpose, and says so.
  </>,
  'She checks whether the job is inside her own remit. If it is, she just answers.',
  <>
    If not, she reads the other teammates&rsquo; <b style={{ fontWeight: 500, color: 'var(--ink)' }}>job titles</b> and
    picks the closest match. The title is the routing key, which is why it is a required field.
  </>,
  <>
    A <b style={{ fontWeight: 500, color: 'var(--ink)' }}>handoff card</b> posts into the thread: who passed it, who
    received it, and why. That card is the receipt for agent-to-agent communication.
  </>,
  'The specialist starts and its dot in the roster turns amber, so you can see who is busy.',
  'If it is missing something — an expired connection, a decision only you can make — it says exactly what it needs and stops. It does not guess a value.',
  'Otherwise it replies in the same thread under its own name and colour.',
  'That reply joins the shared context, readable by every teammate. This is what removes copying between windows.',
];

export default function ArchitecturePage() {
  return (
    <>
      <PageHead
        title="Architecture"
        blurb="How work reaches an agent — on a schedule, or handed over in the team thread — and how it gets from there to a message in your Slack."
        actions={<DownloadDiagramButton />}
      />

      <div className="card" style={{ marginBottom: 16 }}>
        <CardHead
          title="System diagram"
          blurb="Solid lines carry work, dashed lines carry data. Two ways in, one job queue."
          aside={
            <span className="badge ok">
              <i />
              v2 scope
            </span>
          }
        />
        <SystemDiagram />
      </div>

      <div className="cols">
        <div className="card">
          <CardHead
            title="What happens on a run"
            blurb="Start to finish, whichever way the run was triggered"
          />
          <ul className="flowlist">
            {FLOW.map((f, i) => (
              <li key={f.title}>
                <span className="n">{i + 1}</span>
                <span>
                  <b>{f.title}</b>
                  <p>{f.blurb}</p>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="stack">
          <div className="card">
            <CardHead title="Why split the scheduler and workers" />
            <div className="card-body" style={{ fontSize: '13.5px', color: 'var(--ink-2)', lineHeight: 1.6 }}>
              The scheduler only decides what is due, so it stays fast and never blocks. The workers do everything slow.
              Run one scheduler and as many workers as you need.
              <div className="divider" />
              <b style={{ display: 'block', color: 'var(--ink)', fontWeight: 500, marginBottom: 6 }}>
                The failure this prevents
              </b>
              If deciding and doing shared a process, one agent stuck on a slow API would delay every other
              agent&rsquo;s 9am run.
            </div>
          </div>

          <div className="card">
            <CardHead title="Hard limits" />
            <div className="card-body">
              <dl className="kv" style={{ gridTemplateColumns: '1fr auto', fontSize: 13 }}>
                {LIMITS.map(([term, value]) => (
                  <Fragment key={term}>
                    <dt>{term}</dt>
                    <dd>{value}</dd>
                  </Fragment>
                ))}
              </dl>
            </div>
          </div>
        </div>
      </div>

      <PartsTable title="Components" rows={COMPONENTS} />

      <div className="card" style={{ marginTop: 16 }}>
        <CardHead
          title="How a handoff works"
          blurb="What happens between the moment you press send and a second agent replying"
        />
        <div className="card-body">
          <ol
            style={{
              margin: 0,
              paddingLeft: 20,
              fontSize: 14,
              lineHeight: 1.75,
              color: 'var(--ink-2)',
              maxWidth: '70ch',
            }}
          >
            {HANDOFF.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ol>
        </div>
      </div>

      <PartsTable title="Delegation parts" rows={DELEGATION} />
    </>
  );
}
