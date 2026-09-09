'use client';

import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';
import { Fragment, Suspense, useCallback, useState } from 'react';
import { InfoIcon, PlayIcon } from '@/components/icons';
import { MarkdownLite } from '@/components/markdown-lite';
import { LiveLog } from '@/components/runs/live-log';
import { Empty, Loaded, Problem } from '@/components/states';
import { CardHead, PageHead } from '@/components/ui';
import {
  getAgent,
  listAgentRuns,
  pauseAgent,
  resumeAgent,
  runAgent,
} from '@/lib/api/endpoints';
import { useLimits, minutes } from '@/lib/api/use-limits';
import { useLoad } from '@/lib/api/use-load';
import type { Run } from '@/lib/api/schemas';

const RUNNING = new Set(['queued', 'running']);

const agentBusy = (a: { is_running: boolean }): boolean => a.is_running;
const anyRunInFlight = (list: Run[]): boolean => list.some((r) => RUNNING.has(r.status));

export default function AgentDetailPage() {
  // useSearchParams needs a boundary so the static shell can render first.
  return (
    <Suspense fallback={null}>
      <AgentDetail />
    </Suspense>
  );
}

function AgentDetail() {
  const params = useParams<{ id: string }>();
  const agentId = Number(params.id);
  // A notification links here with ?run= so the failing run opens pinned.
  const search = useSearchParams();
  const linked = Number(search.get('run'));

  // null means "whatever is newest"; a click pins a specific run.
  const [pinnedRun, setPinnedRun] = useState<number | null>(
    Number.isInteger(linked) && linked > 0 ? linked : null,
  );
  const [liveRun, setLiveRun] = useState<number | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Both poll only while a run is in flight; the data itself says when to stop.
  const agent = useLoad(useCallback((signal) => getAgent(agentId, signal), [agentId]), {
    pollMs: 3000,
    pollWhile: agentBusy,
  });
  const runs = useLoad(useCallback((signal) => listAgentRuns(agentId, signal), [agentId]), {
    pollMs: 3000,
    pollWhile: anyRunInFlight,
  });
  const limits = useLimits();

  const rows = runs.state.kind === 'ready' ? runs.state.data : [];
  const newest = rows[0];
  // Derived, not stored: the newest run shows until one is pinned.
  const selectedRun = pinnedRun ?? newest?.id ?? null;
  const selected = rows.find((r) => r.id === selectedRun);
  // Follow the stream only while the run is really in flight. If the stream
  // dropped and the run has since finished, the stored log is what to show.
  const liveStatus = liveRun === null ? undefined : rows.find((r) => r.id === liveRun)?.status;
  const following =
    liveRun !== null && (liveStatus === undefined || RUNNING.has(liveStatus))
      ? liveRun
      : newest && RUNNING.has(newest.status)
        ? newest.id
        : null;

  const start = async () => {
    setBusy(true);
    setProblem(null);
    const result = await runAgent(agentId);
    setBusy(false);
    if (!result.ok) {
      setProblem(result.error.message);
      return;
    }
    setPinnedRun(result.data.id);
    setLiveRun(result.data.id);
    runs.reload();
    // The POST returns after the agent is claimed, so this re-read sees
    // is_running=true and the roster-style polling takes over from there.
    agent.reload();
  };

  const togglePause = async (paused: boolean) => {
    setProblem(null);
    const result = paused ? await resumeAgent(agentId) : await pauseAgent(agentId);
    if (!result.ok) setProblem(result.error.message);
    agent.reload();
  };

  const onFinished = useCallback(() => {
    setLiveRun(null);
    runs.reload();
    agent.reload();
  }, [runs, agent]);

  return (
    <Loaded state={agent.state}>
      {(data) => (
        <>
          <PageHead
            title={data.name}
            blurb={data.description || 'No description.'}
            actions={
              <div style={{ display: 'flex', gap: 9 }}>
                <Link className="btn sec" href={`/create?edit=${data.id}`}>
                  Edit
                </Link>
                {data.schedule ? (
                  <button className="btn sec" onClick={() => togglePause(data.schedule!.is_paused)}>
                    {data.schedule.is_paused ? 'Resume' : 'Pause'}
                  </button>
                ) : null}
                <button className="btn" onClick={start} disabled={busy || data.is_running}>
                  <PlayIcon />
                  {data.is_running ? 'Running…' : 'Run now'}
                </button>
              </div>
            }
          />

          {problem ? <Problem message={problem} /> : null}

          <div className="cols">
            <div className="stack">
              <div className="card">
                <CardHead
                  title="Schedule"
                  aside={
                    data.schedule ? (
                      data.schedule.is_paused ? (
                        <span className="badge">Paused</span>
                      ) : (
                        <span className="badge ok">
                          <i />
                          Active
                        </span>
                      )
                    ) : (
                      <span className="badge">Manual only</span>
                    )
                  }
                />
                <div className="card-body">
                  {data.schedule ? (
                    <dl className="kv">
                      <dt>Cron rule</dt>
                      <dd>
                        <span className="mono">{data.schedule.cron}</span>
                        {data.schedule.words ? (
                          <span style={{ color: 'var(--ink-3)', marginLeft: 8 }}>
                            {data.schedule.words}
                          </span>
                        ) : null}
                      </dd>
                      <dt>Timezone</dt>
                      <dd>{data.schedule.timezone}</dd>
                      <dt>Next runs</dt>
                      <dd>
                        {data.schedule.is_paused
                          ? 'Paused'
                          : data.schedule.next_runs.join(' · ') || '—'}
                      </dd>
                      <dt>Retries</dt>
                      <dd>Up to {limits.max_attempts}, backing off {limits.retry_backoff_seconds.map((n) => `${n}s`).join(' / ')}</dd>
                      <dt>Timeout</dt>
                      <dd>{minutes(limits.run_timeout_seconds)}, then cancel</dd>
                    </dl>
                  ) : (
                    <p className="hint" style={{ margin: 0 }}>
                      This agent has no schedule. It runs only when you press Run now, or when the
                      team hands it work.
                    </p>
                  )}
                </div>
              </div>

              <div className="card">
                <CardHead
                  title="Run history"
                  blurb={
                    runs.state.kind === 'ready' ? `Last ${runs.state.data.length} runs` : 'Loading…'
                  }
                />
                <Loaded state={runs.state}>
                  {(rows) =>
                    rows.length === 0 ? (
                      <Empty message="No runs yet. Press Run now and watch the log." />
                    ) : (
                      <ul className="runs">
                        {rows.map((run) => (
                          <li key={run.id}>
                            <button
                              aria-pressed={selectedRun === run.id}
                              onClick={() => {
                                setPinnedRun(run.id);
                                setLiveRun(RUNNING.has(run.status) ? run.id : null);
                              }}
                            >
                              <span className="lft">
                                <StatusBadge run={run} />
                                <span>
                                  <b>{when(run.created_at)}</b>
                                  <span className="sub">
                                    {run.trigger}
                                    {run.attempt > 1 ? ` · attempt ${run.attempt}` : ''}
                                  </span>
                                </span>
                              </span>
                              <span className="mono" style={{ color: 'var(--ink-3)' }}>
                                {run.duration_seconds === null
                                  ? '—'
                                  : `${run.duration_seconds.toFixed(1)}s`}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )
                  }
                </Loaded>
                <LiveLog
                  key={selectedRun ?? 'none'}
                  runId={selectedRun}
                  live={following !== null && following === selectedRun}
                  onFinished={onFinished}
                />
                {selected && (selected.output || selected.error) ? (
                  <div className={`result${selected.status === 'failed' ? ' failed' : ''}`}>
                    <b>{selected.status === 'failed' ? 'What went wrong' : 'Result'}</b>
                    {selected.status === 'failed' ? (
                      <p>{selected.error}</p>
                    ) : (
                      <MarkdownLite text={selected.output ?? ''} />
                    )}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="stack">
              <div className="card">
                <CardHead
                  title="Tools"
                  aside={<span className="badge">{data.tools.length} allowed</span>}
                />
                <div className="card-body" style={{ paddingTop: 6 }}>
                  {data.tools.length === 0 ? (
                    <p className="hint" style={{ margin: 0 }}>
                      No tools. This agent can only answer from its prompt.
                    </p>
                  ) : (
                    data.tools.map((tool) => (
                      <div className="conn" key={tool.tool_name}>
                        <span className="c">
                          <span>
                            <b className="mono" style={{ fontSize: 13 }}>
                              {tool.tool_name}
                            </b>
                          </span>
                        </span>
                        <span className={`tag ${tool.can_write ? 'write' : 'read'}`}>
                          {tool.can_write ? 'writes' : 'read'}
                        </span>
                      </div>
                    ))
                  )}
                  <p className="note">
                    <InfoIcon />
                    <span>
                      A run is capped at {limits.max_tool_calls_per_run} tool calls and {minutes(limits.run_timeout_seconds)}. Anything marked{' '}
                      <b style={{ fontWeight: 800, color: 'var(--run)' }}>writes</b> takes effect in
                      the real app.
                    </span>
                  </p>
                </div>
              </div>

              <div className="card">
                <CardHead
                  title="Instructions"
                  aside={
                    <Link className="btn sec sm" href={`/create?edit=${data.id}`}>
                      Edit
                    </Link>
                  }
                />
                <div className="card-body" style={{ color: 'var(--ink-2)', fontSize: 13 }}>
                  {data.user_prompt || data.system_prompt || 'No prompt set.'}
                  <div className="divider" />
                  <dl className="kv" style={{ gridTemplateColumns: '110px 1fr' }}>
                    <Fragment>
                      <dt>Model</dt>
                      <dd className="mono">{data.model}</dd>
                    </Fragment>
                    <Fragment>
                      <dt>Max calls</dt>
                      <dd>{limits.max_tool_calls_per_run} per run</dd>
                    </Fragment>
                  </dl>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </Loaded>
  );
}

function StatusBadge({ run }: { run: Run }) {
  if (run.status === 'succeeded') {
    return (
      <span className="badge ok">
        <i />
        {run.attempt > 1 ? 'Retried' : 'Succeeded'}
      </span>
    );
  }
  if (run.status === 'failed') {
    return (
      <span className="badge err">
        <i />
        Failed
      </span>
    );
  }
  return (
    <span className="badge run">
      <i />
      {run.status === 'queued' ? 'Queued' : 'Running'}
    </span>
  );
}

function when(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}
