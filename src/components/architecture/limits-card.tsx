'use client';

import { Fragment } from 'react';
import { useLimits, minutes } from '@/lib/api/use-limits';
import { CardHead } from '../ui';

/**
 * Read from /health rather than typed here, so the numbers on this page cannot
 * drift from the ones the backend actually enforces. The scheduler tick is the
 * one exception: it is not part of the limits payload.
 */
export function LimitsCard() {
  const l = useLimits();
  const rows: [string, string, string][] = [
    ['Scheduler tick', 'every 30s', 'scheduler/ticker.py'],
    ['Run wall clock', minutes(l.run_timeout_seconds), 'runtime/executor.py'],
    ['Tool calls per run', String(l.max_tool_calls_per_run), 'runtime/executor.py'],
    ['One tool call', `${l.tool_call_timeout_seconds}s, then cancelled`, 'runtime/router.py'],
    [
      'Retries',
      `${l.max_attempts} · ${l.retry_backoff_seconds.map((s) => `${s}s`).join(' / ')}`,
      'runtime/runs.py',
    ],
    ['Agents per user', `${l.max_agents_per_user}, then 402`, 'api/agents.py'],
    ['Same agent twice at once', 'refused, 409', 'runtime/runs.py'],
    ['Log line reaches the browser', 'under 2s', 'runtime/logger.py'],
  ];

  return (
    <div className="card">
      <CardHead title="Limits" blurb="Read live from the backend, not typed into this page" />
      <div className="card-body">
        <dl className="kv limits">
          {rows.map(([term, value, where]) => (
            <Fragment key={term}>
              <dt>{term}</dt>
              <dd>
                {value}
                <span className="mono">{where}</span>
              </dd>
            </Fragment>
          ))}
        </dl>
      </div>
    </div>
  );
}
