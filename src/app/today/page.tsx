'use client';

import Link from 'next/link';
import { useCallback, useState } from 'react';
import { BusiestAgents, OutcomeRing, RunsPerHourChart } from '@/components/today/charts';
import { Tiles } from '@/components/today/tiles';
import { AlertCircleIcon, RefreshIcon, TokenIcon } from '@/components/icons';
import { plainPreview } from '@/components/markdown-lite';
import { Empty, Loaded } from '@/components/states';
import { CardHead, PageHead, Segmented } from '@/components/ui';
import { getStats, listAgents, listNotifications, notificationHref } from '@/lib/api/endpoints';
import { useLoad } from '@/lib/api/use-load';
import { useAuth } from '@/lib/auth';

const RANGES = ['Today', '7 days', '30 days'] as const;
const RANGE_KEYS = ['today', '7d', '30d'] as const;

function greeting(now: Date): string {
  const hour = now.getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * Fixed English wording, on purpose: this line is server-rendered, and
 * `toLocaleDateString` gave "Tuesday, 8 September" on Node and "Tuesday 8
 * September" in the browser — a hydration mismatch on every load.
 */
function formatLongDate(d: Date): string {
  return `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export default function TodayPage() {
  const [range, setRange] = useState(0);
  const [now] = useState(() => new Date());
  const auth = useAuth();
  const me = auth.state.kind === 'signed-in' ? auth.state.me : null;
  const firstName = (me?.name || me?.email || 'there').split(/[\s@]/)[0];

  const stats = useLoad(useCallback((signal) => getStats(RANGE_KEYS[range], signal), [range]));
  const agents = useLoad(useCallback((signal) => listAgents(signal), []), { pollMs: 5000 });
  const feed = useLoad(useCallback((signal) => listNotifications(signal), []));

  const dateLine = formatLongDate(now);

  const running = agents.state.kind === 'ready' ? agents.state.data.filter((a) => a.is_running) : [];
  const unread =
    feed.state.kind === 'ready' ? feed.state.data.filter((n) => !n.is_read).slice(0, 4) : [];

  return (
    <>
      <PageHead
        title={`${greeting(now)}, ${firstName}`}
        blurb={
          running.length
            ? `${dateLine}. ${running.length} agent${running.length > 1 ? 's are' : ' is'} running.`
            : `${dateLine}. Nothing is running right now.`
        }
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Segmented options={[...RANGES]} active={[range]} onSelect={setRange} />
            <button
              className="btn sec"
              onClick={() => {
                stats.reload();
                agents.reload();
                feed.reload();
              }}
            >
              <RefreshIcon />
              Refresh
            </button>
          </div>
        }
      />

      <Loaded state={stats.state}>{(data) => <Tiles stats={data} />}</Loaded>

      <div className="dash3 first">
        <div className="card">
          <CardHead
            title="Needs attention"
            blurb="Unread, newest first"
            aside={
              unread.length ? (
                <span className="badge err">
                  <i />
                  {unread.length} open
                </span>
              ) : null
            }
          />
          {unread.length === 0 ? (
            <Empty message="Nothing needs you right now." />
          ) : (
            <ul className="attlist">
              {unread.map((n) => (
                <li key={n.id}>
                  <span
                    className="a-ico"
                    style={
                      n.kind === 'failure'
                        ? { background: '#a3231c14', color: '#a3231c' }
                        : { background: '#8a5a0014', color: '#8a5a00' }
                    }
                  >
                    {n.kind === 'failure' ? <AlertCircleIcon /> : <TokenIcon />}
                  </span>
                  <span className="a-txt">
                    <b>{n.title}</b>
                    <p>{plainPreview(n.body)}</p>
                  </span>
                  <Link className="btn sec sm" href={notificationHref(n)}>
                    {n.agent_id === null || n.agent_id === undefined ? 'View' : 'Open run'}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="stack">
          {running.length === 0 ? (
            <div className="card">
              <CardHead title="Running now" />
              <Empty message="No agent is running. Press Run now on an agent to watch it live." />
            </div>
          ) : (
            running.slice(0, 1).map((agent) => (
              <div className="live" key={agent.id}>
                <div className="live-top">
                  <span className="badge run">
                    <i />
                    Running now
                  </span>
                  <span className="live-el">{agent.model}</span>
                </div>
                <b className="live-name">{agent.name}</b>
                <p className="live-step">{agent.description || 'In progress…'}</p>
                <div className="bar indeterminate" aria-hidden="true">
                  <i />
                </div>
                <div className="live-foot">
                  <span>
                    {running.length} of {agents.state.kind === 'ready' ? agents.state.data.length : 0}{' '}
                    agents busy
                  </span>
                  <Link className="btn sec sm" href={`/agents/${agent.id}`}>
                    Watch
                  </Link>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <Loaded state={stats.state}>
        {(data) => (
          <div className="dash2">
            <div className="card">
              <CardHead
                title="Runs per hour"
                blurb="Last 24 hours across all agents"
                aside={<span className="badge">{data.runs_today} today</span>}
              />
              <RunsPerHourChart buckets={data.runs_per_hour} />
            </div>

            <div className="stack">
              <div className="card">
                <CardHead title="Outcomes" blurb={RANGES[range]} />
                <div className="card-body">
                  <OutcomeRing outcomes={data.outcomes} successRate={data.success_rate} />
                </div>
              </div>
              <div className="card">
                <CardHead title="Busiest agents" blurb={RANGES[range]} />
                <div className="card-body">
                  <BusiestAgents agents={data.busiest_agents} />
                </div>
              </div>
            </div>
          </div>
        )}
      </Loaded>
    </>
  );
}
