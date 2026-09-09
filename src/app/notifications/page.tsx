'use client';

import Link from 'next/link';
import { useCallback, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertCircleIcon, CheckIcon, ClockCircleIcon, RefreshIcon, TokenIcon } from '@/components/icons';
import { MarkdownLite } from '@/components/markdown-lite';
import { Empty, Loaded, Problem } from '@/components/states';
import { CardHead, PageHead, Switch } from '@/components/ui';
import {
  getPrefs,
  listNotifications,
  markAllRead,
  markRead,
  notificationHref,
  putPrefs,
} from '@/lib/api/endpoints';
import type { Prefs } from '@/lib/api/schemas';
import { useLoad } from '@/lib/api/use-load';

function iconFor(kind: string): { node: ReactNode; colour: string } {
  if (kind === 'failure') return { node: <AlertCircleIcon size={15} strokeWidth={2.2} />, colour: 'var(--err)' };
  if (kind === 'expiry') return { node: <TokenIcon size={15} strokeWidth={2.2} />, colour: 'var(--run)' };
  return { node: <CheckIcon size={15} />, colour: 'var(--ok)' };
}

export default function NotificationsPage() {
  const feed = useLoad(useCallback((signal) => listNotifications(signal), []));
  const prefsLoad = useLoad(useCallback((signal) => getPrefs(signal), []));

  // The loaded value is the source of truth; `pending` holds the optimistic
  // edit until the PUT lands, so nothing is copied into state by an effect.
  const [pending, setPending] = useState<Prefs | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  // Rows read on this page, before the feed is fetched again.
  const [readHere, setReadHere] = useState<Set<number>>(() => new Set());
  // A run's full output can be a screen long; long bodies start folded.
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());
  const LONG = 320;

  const open = async (id: number) => {
    setReadHere((prev) => new Set(prev).add(id));
    const result = await markRead(id);
    if (!result.ok) setProblem(result.error.message);
  };

  const prefs: Prefs | null =
    pending ?? (prefsLoad.state.kind === 'ready' ? prefsLoad.state.data : null);

  /* Preferences save as they change — the screen has no save button. */
  const save = async (next: Prefs) => {
    setPending(next);
    const result = await putPrefs(next);
    if (!result.ok) setProblem(result.error.message);
  };

  const rows = feed.state.kind === 'ready' ? feed.state.data : [];
  const isRead = (n: { id: number; is_read: boolean }) => n.is_read || readHere.has(n.id);
  const unread = rows.filter((n) => !isRead(n)).length;
  const failures = rows.filter((n) => n.kind === 'failure').length;

  const metrics = [
    { cls: 'g3', label: 'Unread', value: unread, colour: 'var(--err)', icon: <AlertCircleIcon size={15} strokeWidth={2.4} /> },
    { cls: 'g4', label: 'Failures', value: failures, colour: 'var(--run)', icon: <ClockCircleIcon size={15} strokeWidth={2.4} /> },
    { cls: 'g2', label: 'Delivered', value: rows.length, colour: 'var(--ok)', icon: <CheckIcon size={15} /> },
  ];

  return (
    <>
      <PageHead
        title="Notifications"
        blurb="What your agents have been trying to tell you."
        actions={
          <button
            className="btn sec"
            onClick={async () => {
              await markAllRead();
              feed.reload();
            }}
            disabled={unread === 0}
          >
            <RefreshIcon />
            Mark all as read
          </button>
        }
      />

      {problem ? <Problem message={problem} /> : null}

      <div className="metrics" style={{ gridTemplateColumns: 'repeat(3,1fr)' }}>
        {metrics.map((m) => (
          <div className={`metric ${m.cls}`} key={m.label}>
            <div className="mtop">
              <span className="mico" style={{ background: m.colour }}>
                {m.icon}
              </span>
              {m.label}
            </div>
            <strong>{m.value}</strong>
          </div>
        ))}
      </div>

      <div className="cols">
        <div className="card">
          <CardHead
            title="Recent"
            blurb="Newest first"
            aside={unread ? <span className="badge run"><i />{unread} unread</span> : null}
          />
          <Loaded state={feed.state}>
            {(list) =>
              list.length === 0 ? (
                <Empty message="Nothing yet. A failed run or an expiring connection will show up here." />
              ) : (
                <ul className="feed">
                  {list.map((n) => {
                    const look = iconFor(n.kind);
                    const read = isRead(n);
                    const hasRun = n.agent_id !== null && n.agent_id !== undefined;
                    return (
                      <li key={n.id}>
                        {read ? (
                          <span style={{ width: 7, flex: '0 0 auto' }} />
                        ) : (
                          <span className="unread" />
                        )}
                        <span className="fico" style={{ background: look.colour }}>
                          {look.node}
                        </span>
                        <span style={{ minWidth: 0, flex: 1 }}>
                          <b>{n.title}</b>
                          <div className={`feed-body${n.body.length > LONG && !expanded.has(n.id) ? ' folded' : ''}`}>
                            <MarkdownLite text={n.body} />
                          </div>
                          {n.body.length > LONG ? (
                            <button
                              className="link"
                              style={{ fontSize: 12, marginTop: 4 }}
                              onClick={() =>
                                setExpanded((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(n.id)) next.delete(n.id);
                                  else next.add(n.id);
                                  return next;
                                })
                              }
                            >
                              {expanded.has(n.id) ? 'Show less' : 'Show more'}
                            </button>
                          ) : null}
                          {n.agent_name ? <span className="sub">{n.agent_name}</span> : null}
                        </span>
                        <span className="feed-right">
                          <time>{new Date(n.at).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</time>
                          <span style={{ display: 'flex', gap: 6 }}>
                            {hasRun ? (
                              <Link
                                className="btn sec sm"
                                href={notificationHref(n)}
                                onClick={() => {
                                  if (!read) void open(n.id);
                                }}
                              >
                                Open run
                              </Link>
                            ) : null}
                            {!read ? (
                              <button className="btn sec sm" onClick={() => void open(n.id)}>
                                Mark read
                              </button>
                            ) : null}
                          </span>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )
            }
          </Loaded>
        </div>

        <div className="stack">
          <div className="card">
            <CardHead title="Delivery" blurb="Saved as you change them" />
            {prefs === null ? (
              <Empty message="Loading preferences…" />
            ) : (
              <div className="card-body" style={{ paddingTop: 4 }}>
                <div className="trow">
                  <span className="tleft">
                    <span>
                      <b>Email</b>
                      <span>{prefs.email_to || 'Your account email'}</span>
                    </span>
                  </span>
                  <Switch
                    pressed={prefs.email_on}
                    label="Email"
                    onToggle={() => void save({ ...prefs, email_on: !prefs.email_on })}
                  />
                </div>
                <div className="trow">
                  <span className="tleft">
                    <span>
                      <b>Slack DM</b>
                      <span>Through your own Slack connection</span>
                    </span>
                  </span>
                  <Switch
                    pressed={prefs.slack_dm_on}
                    label="Slack DM"
                    onToggle={() => void save({ ...prefs, slack_dm_on: !prefs.slack_dm_on })}
                  />
                </div>
                <div className="trow">
                  <span className="tleft">
                    <span>
                      <b>Webhook</b>
                      <span>{prefs.webhook_url || 'Not configured'}</span>
                    </span>
                  </span>
                  <Switch
                    pressed={prefs.webhook_on}
                    label="Webhook"
                    onToggle={() => void save({ ...prefs, webhook_on: !prefs.webhook_on })}
                  />
                </div>
                <div className="trow">
                  <span className="tleft">
                    <span>
                      <b>Every successful run</b>
                      <span>Noisy on frequent schedules. Off by default.</span>
                    </span>
                  </span>
                  <Switch
                    pressed={prefs.notify_on_success}
                    label="Notify on success"
                    onToggle={() => void save({ ...prefs, notify_on_success: !prefs.notify_on_success })}
                  />
                </div>
              </div>
            )}
          </div>

          <div className="card">
            <CardHead title="Quiet hours" />
            <div className="card-body" style={{ paddingTop: 14 }}>
              <p className="hint" style={{ marginBottom: 12 }}>
                Nothing but failures gets through during these hours.
              </p>
              {prefs === null ? null : (
                <div className="row2">
                  <div className="fld" style={{ marginBottom: 0 }}>
                    <label htmlFor="qs">From</label>
                    <input
                      className="inp"
                      id="qs"
                      type="time"
                      value={prefs.quiet_from ?? ''}
                      onChange={(e) => void save({ ...prefs, quiet_from: e.target.value || null })}
                    />
                  </div>
                  <div className="fld" style={{ marginBottom: 0 }}>
                    <label htmlFor="qe">Until</label>
                    <input
                      className="inp"
                      id="qe"
                      type="time"
                      value={prefs.quiet_to ?? ''}
                      onChange={(e) => void save({ ...prefs, quiet_to: e.target.value || null })}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
