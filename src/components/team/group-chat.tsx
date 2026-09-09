'use client';

import { useEffect, useImperativeHandle, useRef, useState } from 'react';
import { SendIcon } from '../icons';
import { Problem } from '../states';
import { CardHead } from '../ui';
import { ThreadView } from './thread-view';
import { useTeam } from '@/lib/team-store';

const initials = (n: string) => n.slice(0, 2).toUpperCase();

const SUGGESTIONS = ['Anything urgent in my inbox today?', 'Who does what on this team?'];

export type ChatHandle = { mention: (name: string) => void };

export function GroupChat({ handleRef }: { handleRef: React.RefObject<ChatHandle | null> }) {
  const { team, thread, problem, send, reset } = useTeam();

  const [input, setInput] = useState('');
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  // The message in flight, drawn at once; it comes off when the server's own
  // copy (any newer user row) is in the thread.
  const [pending, setPending] = useState<{ text: string; after: number } | null>(null);

  const threadRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  useImperativeHandle(
    handleRef,
    () => ({
      mention: (name: string) => {
        setInput(`@${name} `);
        inputRef.current?.focus();
      },
    }),
    [],
  );

  const messages = thread.kind === 'ready' ? thread.data : [];
  const roster = team.kind === 'ready' ? team.data : null;
  const optimistic =
    pending && !messages.some((m) => m.kind === 'user' && m.id > pending.after)
      ? pending.text
      : null;

  // Stay pinned to the newest message. Row heights settle after the roster
  // (names, titles) arrives, so a one-off scrollTop write on message count
  // landed short; a ResizeObserver re-pins whenever the content grows, unless
  // the user has deliberately scrolled up to read history.
  useEffect(() => {
    const box = threadRef.current;
    if (!box) return;
    const pin = () => {
      const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
      if (nearBottom) box.scrollTo({ top: box.scrollHeight, behavior: 'instant' });
    };
    box.scrollTo({ top: box.scrollHeight, behavior: 'instant' });
    const observer = new ResizeObserver(pin);
    for (const child of Array.from(box.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [messages.length, roster, optimistic]);

  const submit = async (raw?: string) => {
    const text = (raw ?? input).trim();
    if (!text || sending) return;
    setSending(true);
    setInput('');
    setMentionQuery(null);
    setPending({ text, after: messages.length ? messages[messages.length - 1].id : 0 });
    if (inputRef.current) inputRef.current.style.height = 'auto';
    const ok = await send(text);
    // A failed send must not leave a phantom bubble; the error shows below.
    if (!ok) setPending(null);
    setSending(false);
  };

  const matches = (() => {
    if (mentionQuery === null || !roster) return [];
    const q = mentionQuery.toLowerCase();
    const others = roster.teammates.filter((m) => !m.is_lead);
    const starts = others.filter((m) => m.display_name.toLowerCase().startsWith(q));
    if (starts.length) return starts;
    return others.filter((m) =>
      `${m.display_name} ${m.job_title}`.toLowerCase().includes(q),
    );
  })();

  const pickMention = (name: string) => {
    setInput((prev) => prev.replace(/@\w*$/, `@${name} `));
    setMentionQuery(null);
    inputRef.current?.focus();
  };

  const suggestions = (() => {
    const list = [...SUGGESTIONS];
    const first = roster?.teammates.find((m) => !m.is_lead);
    if (first) list.push(`@${first.display_name} what are you picking up today?`);
    return list;
  })();

  return (
    <div className="card">
      <CardHead
        title="Group chat"
        blurb="One thread the whole team can read"
        aside={
          <button className="btn sec sm" onClick={() => void reset()}>
            Clear thread
          </button>
        }
      />

      <ThreadView thread={messages} team={roster} pending={optimistic} ref={threadRef} />

      {problem ? <Problem message={problem} /> : null}

      <div className="tsuggest">
        {suggestions.map((s) => (
          <button key={s} onClick={() => void submit(s)}>
            {s}
          </button>
        ))}
      </div>

      <div className="tcompose" style={{ position: 'relative' }}>
        {matches.length ? (
          <div className="mentions">
            {matches.map((m) => (
              <button key={m.id} onClick={() => pickMention(m.display_name)}>
                <span className="ava" style={{ background: m.colour }}>
                  {initials(m.display_name)}
                </span>
                <span>
                  <b style={{ fontWeight: 500 }}>{m.display_name}</b> <em>{m.job_title}</em>
                </span>
              </button>
            ))}
          </div>
        ) : null}
        <textarea
          ref={inputRef}
          rows={1}
          placeholder="Ask the team something, or type @ to pick a teammate…"
          aria-label="Message the team"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            e.target.style.height = 'auto';
            e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
            const tail = e.target.value.slice(0, e.target.selectionStart ?? 0).match(/@(\w*)$/);
            setMentionQuery(tail ? tail[1] : null);
          }}
          onKeyDown={(e) => {
            if (matches.length && (e.key === 'Enter' || e.key === 'Tab')) {
              e.preventDefault();
              pickMention(matches[0].display_name);
              return;
            }
            if (e.key === 'Escape') {
              setMentionQuery(null);
              return;
            }
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <button
          className="send"
          aria-label="Send"
          disabled={input.trim() === '' || sending}
          onClick={() => void submit()}
        >
          <SendIcon />
        </button>
      </div>
    </div>
  );
}
