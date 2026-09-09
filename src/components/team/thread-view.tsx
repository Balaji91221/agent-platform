'use client';

import Link from 'next/link';
import { forwardRef } from 'react';
import { ArrowRightIcon, BlockedIcon, ClockCircleIcon } from '../icons';
import { MarkdownLite } from '../markdown-lite';
import { useAuth } from '@/lib/auth';
import type { Team, TeamMessage, Teammate } from '@/lib/api/schemas';

const PICKED_UP = 'Picked it up.';

const initials = (n: string) => {
  const words = n.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return n.slice(0, 2).toUpperCase();
};

type Props = {
  thread: TeamMessage[];
  team: Team | null;
  /** A message the user just sent, shown until the server's copy arrives. */
  pending: string | null;
};

/** Teammates mid-task for the room: running, and their last word was "Picked it up." */
function working(team: Team | null, thread: TeamMessage[]): Teammate[] {
  if (!team) return [];
  return team.teammates.filter((mate) => {
    if (!mate.is_running) return false;
    const last = [...thread]
      .reverse()
      .find((m) => m.from_teammate_id === mate.id && m.kind !== 'queued');
    return last?.kind === 'agent' && last.text === PICKED_UP;
  });
}

export const ThreadView = forwardRef<HTMLDivElement, Props>(function ThreadView(
  { thread, team, pending },
  ref,
) {
  const { state } = useAuth();
  const me =
    state.kind === 'signed-in' ? initials(state.me.name || state.me.email) : 'ME';

  const mateOf = (id: number | null) =>
    id === null ? undefined : team?.teammates.find((m) => m.id === id);
  const lead = team?.teammates.find((m) => m.is_lead);
  const busy = working(team, thread);

  return (
    <div className="tthread" ref={ref}>
      {thread.length === 0 && !pending ? (
        <div className="tempty">
          <b>Nothing in the room yet.</b>
          <span>
            Send a message and the lead reads it, answers, or hands it to whoever&apos;s job it
            is. Type @ to talk to one teammate directly.
          </span>
        </div>
      ) : null}

      {thread.map((item) => {
        if (item.kind === 'user') {
          return (
            <div className="tmsg me" key={item.id}>
              <span className="ava">{me}</span>
              <div className="body">
                <div className="txt">{item.text}</div>
              </div>
            </div>
          );
        }

        if (item.kind === 'no_lead') {
          return (
            <div className="handoff blocked-note" key={item.id}>
              <span className="hi">
                <BlockedIcon />
              </span>
              <span>
                <b>Nobody claimed this.</b>
                <span className="why">{item.text}</span>
              </span>
            </div>
          );
        }

        if (item.kind === 'handoff') {
          const from = mateOf(item.from_teammate_id);
          const to = mateOf(item.to_teammate_id);
          return (
            <div className="handoff" key={item.id}>
              <span className="hi">
                <ArrowRightIcon />
              </span>
              <span>
                <b>{from?.display_name ?? 'The lead'}</b> handed this to{' '}
                <b>{to?.display_name ?? 'a former teammate'}</b>
                <span className="why">{item.text}</span>
              </span>
            </div>
          );
        }

        if (item.kind === 'queued') {
          const mate = mateOf(item.from_teammate_id);
          return (
            <div className="handoff queued-note" key={item.id}>
              <span className="hi">
                <ClockCircleIcon />
              </span>
              <span>
                <b>{mate?.display_name ?? 'A former teammate'} is busy, so this is queued</b>
                <span className="why">
                  Starts the moment the current task ends: &ldquo;{item.text}&rdquo;
                </span>
              </span>
            </div>
          );
        }

        if (item.kind === 'blocked') {
          const mate = mateOf(item.from_teammate_id);
          return (
            <div className="handoff blocked-note" key={item.id}>
              <span className="hi">
                <BlockedIcon />
              </span>
              <span>
                <b>{mate?.display_name ?? 'A former teammate'} stopped</b>
                <span className="why">{item.text}</span>
              </span>
            </div>
          );
        }

        const mate = mateOf(item.from_teammate_id);
        const picked = item.text === PICKED_UP;
        return (
          <div className={`tmsg${picked ? ' picked' : ''}`} key={item.id}>
            <span className="ava" style={{ background: mate?.colour ?? '#9aa0a6' }}>
              {mate ? initials(mate.display_name) : '—'}
            </span>
            <div className="body">
              <div className="from" style={{ color: mate?.colour ?? 'var(--ink-3)' }}>
                {mate?.display_name ?? 'Former teammate'} <em>{mate?.job_title ?? 'removed from the team'}</em>
              </div>
              <div className="txt">
                <MarkdownLite text={item.text} />
              </div>
              {item.run_id !== null && !picked && mate ? (
                <Link className="runlink" href={`/agents/${mate.agent_id}`}>
                  From run r_{item.run_id}
                </Link>
              ) : null}
            </div>
          </div>
        );
      })}

      {pending ? (
        <div className="tmsg me" key="pending">
          <span className="ava">{me}</span>
          <div className="body">
            <div className="txt">{pending}</div>
          </div>
        </div>
      ) : null}

      {pending && lead && !pending.startsWith('@') ? (
        <Typing mate={lead} label="reading this" />
      ) : null}

      {busy.map((mate) => (
        <Typing key={`working-${mate.id}`} mate={mate} label="working on it" />
      ))}
    </div>
  );
});

function Typing({ mate, label }: { mate: Teammate; label: string }) {
  return (
    <div className="tmsg working" aria-live="polite">
      <span className="ava" style={{ background: mate.colour }}>
        {initials(mate.display_name)}
      </span>
      <div className="body">
        <div className="from" style={{ color: mate.colour }}>
          {mate.display_name} <em>{label}…</em>
        </div>
        <div className="typing">
          <s />
          <s />
          <s />
        </div>
      </div>
    </div>
  );
}
