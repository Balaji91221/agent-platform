'use client';

import { useCallback, useState } from 'react';
import { Loaded, Problem } from '@/components/states';
import { CardHead } from '@/components/ui';
import { deployAgent, getDeployment } from '@/lib/api/endpoints';
import type { A2A, Deployment, JobRun, JobStatus } from '@/lib/api/schemas';
import { useLoad } from '@/lib/api/use-load';

/** Friendlier than the Jenkins job name, which is what the backend returns. */
const JOB_LABELS: Record<string, string> = {
  'agent-create': 'Create',
  'agent-deploy': 'Deploy',
  'agent-delete': 'Delete',
};

type BadgeLook = { className: string; text: string };

function look(status: JobStatus): BadgeLook {
  switch (status) {
    case 'success':
      return { className: 'badge ok', text: 'Passed' };
    case 'running':
      return { className: 'badge run', text: 'Running' };
    case 'queued':
      return { className: 'badge', text: 'Queued' };
    case 'none':
      return { className: 'badge', text: 'Not run' };
    case 'failure':
      return { className: 'badge err', text: 'Failed' };
    case 'unavailable':
      return { className: 'badge err', text: 'Jenkins down' };
    case 'disabled':
      return { className: 'badge', text: 'Off' };
    default: {
      const exhaustive: never = status;
      throw new Error(`unhandled job status: ${String(exhaustive)}`);
    }
  }
}

/** Keep polling while any build is still moving; the data says when to stop. */
const anyJobInFlight = (d: Deployment): boolean =>
  d.jobs.some((j) => j.status === 'running' || j.status === 'queued');

function JobRow({ run }: { run: JobRun }) {
  const badge = look(run.status);
  return (
    <li className="row">
      <span>{JOB_LABELS[run.job] ?? run.job}</span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {run.url ? (
          <a className="link mono" href={run.url} target="_blank" rel="noreferrer">
            #{run.build_number}
          </a>
        ) : (
          <span style={{ color: 'var(--ink-3)' }}>{run.message || '—'}</span>
        )}
        <span className={badge.className}>
          {run.status === 'success' || run.status === 'running' ? <i /> : null}
          {badge.text}
        </span>
      </span>
    </li>
  );
}

/** The token is a live credential, so it stays hidden until asked for. */
function A2ASection({ a2a }: { a2a: A2A }) {
  const [shown, setShown] = useState(false);

  if (!a2a.enabled) {
    return (
      <p className="hint" style={{ margin: '12px 0 0' }}>
        A2A is off. Set <span className="mono">A2A_ENABLED=true</span> to let other agents call
        this one.
      </p>
    );
  }

  return (
    <dl className="kv" style={{ marginTop: 14 }}>
      <dt>Agent card</dt>
      <dd>
        <a className="link mono" href={a2a.card_url} target="_blank" rel="noreferrer">
          {a2a.card_url}
        </a>
      </dd>
      <dt>Token</dt>
      <dd style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="mono">{shown ? a2a.token : '•'.repeat(24)}</span>
        <button className="btn sec sm" onClick={() => setShown((v) => !v)}>
          {shown ? 'Hide' : 'Show'}
        </button>
      </dd>
    </dl>
  );
}

export function DeploymentCard({ agentId }: { agentId: number }) {
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const deployment = useLoad(
    useCallback((signal: AbortSignal) => getDeployment(agentId, signal), [agentId]),
    { pollMs: 4000, pollWhile: anyJobInFlight },
  );

  const deploy = async () => {
    setBusy(true);
    setProblem(null);
    const result = await deployAgent(agentId);
    setBusy(false);
    if (!result.ok) {
      setProblem(result.error.message);
      return;
    }
    deployment.reload();
  };

  return (
    <div className="card">
      <CardHead
        title="Deployment"
        blurb="Jenkins jobs, the host entry, and how other agents reach this one."
        aside={
          <button className="btn sec sm" onClick={deploy} disabled={busy}>
            {busy ? 'Deploying…' : 'Deploy'}
          </button>
        }
      />
      <div className="card-body">
        {problem ? <Problem message={problem} /> : null}
        <Loaded state={deployment.state}>
          {(data) => (
            <>
              <dl className="kv">
                <dt>Host entry</dt>
                <dd>
                  <span className="mono">{data.host_entry}</span>
                </dd>
                <dt>Hosts file</dt>
                <dd>
                  <span className="mono">{data.hosts_file}</span>
                </dd>
              </dl>
              <ul className="runs" style={{ marginTop: 14, borderTop: '1px solid var(--outline-2)' }}>
                {data.jobs.map((job) => (
                  <JobRow key={job.job} run={job} />
                ))}
              </ul>
              <A2ASection a2a={data.a2a} />
              {data.enabled ? null : (
                <p className="hint" style={{ margin: '8px 0 0' }}>
                  Jenkins is off. Set <span className="mono">JENKINS_ENABLED=true</span> and run{' '}
                  <span className="mono">docker compose up -d jenkins</span> to turn these on.
                </p>
              )}
            </>
          )}
        </Loaded>
      </div>
    </div>
  );
}
