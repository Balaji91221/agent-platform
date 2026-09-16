import type { ReactNode } from 'react';
import { SystemDiagram } from '@/components/architecture/diagram';
import { DownloadDiagramButton } from '@/components/architecture/download-button';
import { LimitsCard } from '@/components/architecture/limits-card';
import { RoutingCard } from '@/components/architecture/routing';
import { FourWaysIn } from '@/components/architecture/starts';
import { COMPONENTS, DELEGATION, PartsTable } from '@/components/architecture/tables';
import { CardHead, PageHead } from '@/components/ui';

const FLOW: { title: string; blurb: ReactNode }[] = [
  {
    title: 'A job reaches a free worker',
    blurb:
      'Workers are separate processes. Add more and more agents run at once; the scheduler never has to grow with them.',
  },
  {
    title: 'The prompts are filled in',
    blurb: (
      <>
        <span className="mono">{'{{now}}'}</span>, <span className="mono">{'{{last_run}}'}</span> and{' '}
        <span className="mono">{'{{agent_name}}'}</span> are replaced with real values before the model sees anything,
        which is why an agent can state the time instead of inventing one.
      </>
    ),
  },
  {
    title: 'The model gets the prompts and the allowed tools',
    blurb:
      'It replies with an answer, or with one tool it wants called. It only ever sees the tools that agent was granted.',
  },
  {
    title: 'The tool router decides who handles the call',
    blurb: (
      <>
        A built-in name like <span className="mono">gmail.list_unread</span> goes to that connector. Anything discovered
        from an MCP server goes to the MCP client. The model cannot tell the difference.
      </>
    ),
  },
  {
    title: 'The credential is decrypted for that one call',
    blurb:
      'The router loads the connection, decrypts the token, and makes the real request. An expired connection raises rather than quietly calling unauthenticated.',
  },
  {
    title: 'The result goes back and the loop repeats',
    blurb: 'Until the model is done, or the tool-call cap is reached, or the run runs out of wall clock.',
  },
  {
    title: 'Every step is written as it happens',
    blurb:
      'Each line lands in the run log and is published on the run’s channel, so an open page shows it in under two seconds.',
  },
  {
    title: 'The ending is dealt with',
    blurb:
      'A failure is retried with backoff. Then the next due time is computed, any team reply is posted before the lock is released, a held message is started, and the notifier is handed anything worth telling you.',
  },
];

export default function ArchitecturePage() {
  return (
    <>
      <PageHead
        title="Architecture"
        blurb="Two programs and one HTTP boundary. The browser holds no credentials and calls nothing but Relay; the backend makes every outside call."
        actions={<DownloadDiagramButton />}
      />

      <div className="card" style={{ marginBottom: 16 }}>
        <CardHead
          title="System diagram"
          blurb="Solid lines carry work, dashed lines carry data. Read it top to bottom: a request enters, a job is queued, a worker does the slow part."
        />
        <SystemDiagram />
      </div>

      <FourWaysIn />

      <div className="cols" style={{ marginTop: 16 }}>
        <div className="card">
          <CardHead title="What happens on a run" blurb="Identical whichever way the run was triggered" />
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
            <CardHead title="Why four processes" />
            <div className="card-body arch-prose">
              The API answers in milliseconds. The scheduler only decides what is due, so it can never get stuck. The
              workers do everything slow. The notifier talks to a mail provider that may hang.
              <div className="divider" />
              <b>The failure this prevents</b>
              One agent stuck on a slow API delaying every other agent’s 9am run. Split apart, it delays only itself.
            </div>
          </div>

          <LimitsCard />

          <div className="card">
            <CardHead title="Two rules that hold everywhere" />
            <div className="card-body arch-prose">
              <b>Credentials</b>
              Encrypted before they are written, decrypted only in the moment before a call. Four kinds share one store:
              OAuth tokens, API keys, custom headers, and MCP bearer tokens.
              <div className="divider" />
              <b>Ownership</b>
              Every query for your data is filtered by user in the database layer, not hidden by the UI. Another
              account’s id returns 404, never 403.
            </div>
          </div>
        </div>
      </div>

      <RoutingCard />

      <PartsTable
        title="Components"
        blurb="Every part, and the file to open when you want to change it"
        rows={COMPONENTS}
      />

      <PartsTable
        title="How a team is put together"
        blurb="Agents do the work; these pieces decide which one, and make that decision visible"
        rows={DELEGATION}
      />
    </>
  );
}
