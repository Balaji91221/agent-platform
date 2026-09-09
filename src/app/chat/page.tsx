'use client';

import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';
import { BigSparkleIcon, PlusIcon, SendIcon, SparkleIcon } from '@/components/icons';
import { MarkdownLite } from '@/components/markdown-lite';
import { Problem } from '@/components/states';
import { DRAFT_KEY } from '@/app/create/page';
import { buildDraft, createAgent, listTools } from '@/lib/api/endpoints';
import type { DraftTurn } from '@/lib/api/endpoints';
import type { AgentDraft } from '@/lib/api/schemas';
import { useAuth } from '@/lib/auth';

type Message =
  | { kind: 'me'; id: number; text: string }
  | { kind: 'reply'; id: number; text: string }
  | { kind: 'bot'; id: number; draft: AgentDraft }
  | { kind: 'typing'; id: number };

const SUGGESTIONS = [
  'Summarise my inbox each morning and post it to Slack',
  'Watch for overdue invoices and draft the reminder',
  'Triage new support tickets and escalate the urgent ones',
];

export default function ChatPage() {
  const router = useRouter();

  const [messages, setMessages] = useState<Message[]>([]);
  const [showExamples, setShowExamples] = useState(false);
  const auth = useAuth();
  const me = auth.state.kind === 'signed-in' ? auth.state.me : null;
  const initials = (me?.name || me?.email || '?')
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('');
  const [draft, setDraft] = useState<AgentDraft | null>(null);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const nextId = useRef(1);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const take = () => {
    const id = nextId.current;
    nextId.current += 1;
    return id;
  };

  const submit = async (raw?: string) => {
    const text = (raw ?? input).trim();
    if (!text || busy) return;

    setProblem(null);
    setInput('');
    if (inputRef.current) inputRef.current.style.height = 'auto';

    // What the model gets to see of the conversation, oldest first. A draft
    // card counts as the assistant having proposed that agent.
    const history: DraftTurn[] = messages.flatMap((m): DraftTurn[] => {
      if (m.kind === 'me') return [{ role: 'user', text: m.text }];
      if (m.kind === 'reply') return [{ role: 'assistant', text: m.text }];
      if (m.kind === 'bot') return [{ role: 'assistant', text: `Drafted agent "${m.draft.name}": ${m.draft.description}` }];
      return [];
    });

    const typingId = take();
    setMessages((prev) => [...prev, { kind: 'me', id: take(), text }, { kind: 'typing', id: typingId }]);
    setBusy(true);

    const result = await buildDraft(text, history);
    setBusy(false);

    if (!result.ok) {
      setMessages((prev) => prev.filter((m) => m.id !== typingId));
      setProblem(result.error.message);
      return;
    }

    // A reply leaves any earlier draft in place; only a new draft replaces it.
    const answer = result.data;
    if (answer.kind === 'draft') setDraft(answer.draft);
    setMessages((prev) =>
      prev.map((m) =>
        m.id !== typingId
          ? m
          : answer.kind === 'draft'
            ? { kind: 'bot', id: typingId, draft: answer.draft }
            : { kind: 'reply', id: typingId, text: answer.text },
      ),
    );
    requestAnimationFrame(() => {
      const box = threadRef.current;
      if (box) box.scrollTop = box.scrollHeight;
    });
  };

  const create = async () => {
    if (!draft) return;
    setBusy(true);
    setProblem(null);
    // The builder only adds a write tool when the task asks for the write
    // ("post to Slack"), so grant it; the form still lets the user revoke it.
    const catalogue = await listTools();
    const writes = new Set(
      catalogue.ok ? catalogue.data.filter((t) => t.writes).map((t) => t.name) : [],
    );
    const result = await createAgent({
      name: draft.name,
      description: draft.description,
      system_prompt: draft.system_prompt,
      user_prompt: draft.user_prompt,
      model: draft.model,
      tools: draft.tools.map((t) => ({ tool_name: t, can_write: writes.has(t) })),
      schedule: { cron: draft.cron, timezone: draft.timezone, is_paused: false },
    });
    setBusy(false);
    if (!result.ok) {
      setProblem(result.error.message);
      return;
    }
    router.push(`/agents/${result.data.id}`);
  };

  const openInForm = () => {
    if (!draft) return;
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    router.push('/create');
  };

  const started = messages.length > 0;

  return (
    <div className="chatpage">
      {!started ? (
        <div className="hero">
          <div className="hero-mark">
            <BigSparkleIcon />
          </div>
          <h1 className="hero-h">What should your agent do?</h1>
          <p className="hero-p">
            Describe it in plain words. The backend writes the prompts, picks a schedule, and hands
            you a draft.
          </p>
        </div>
      ) : null}

      <div className="thread" ref={threadRef}>
        {messages.map((m) => {
          if (m.kind === 'me') {
            return (
              <div className="msg me" key={m.id}>
                <span className="ava">{initials}</span>
                <div className="bub">
                  <MarkdownLite text={m.text} />
                </div>
              </div>
            );
          }
          if (m.kind === 'reply') {
            return (
              <div className="msg bot" key={m.id}>
                <span className="ava">
                  <SparkleIcon />
                </span>
                <div className="bub">
                  <MarkdownLite text={m.text} />
                </div>
              </div>
            );
          }
          if (m.kind === 'typing') {
            return (
              <div className="msg bot" key={m.id}>
                <span className="ava">
                  <SparkleIcon />
                </span>
                <div className="bub">
                  <div className="typing">
                    <s />
                    <s />
                    <s />
                  </div>
                </div>
              </div>
            );
          }
          return (
            <div className="msg bot" key={m.id}>
              <span className="ava">
                <SparkleIcon />
              </span>
              <div className="bub">
                <p>
                  Here is <b>{m.draft.name}</b>.
                </p>
                <p>{m.draft.description}</p>
                <p>
                  <span className="mono">{m.draft.cron}</span> &nbsp;{m.draft.timezone} · model{' '}
                  <span className="mono">{m.draft.model}</span>
                </p>
                <p>Create it below, or open it in the form to edit the prompts by hand.</p>
              </div>
            </div>
          );
        })}
      </div>

      {problem ? <Problem message={problem} /> : null}

      <div className="box">
        <textarea
          ref={inputRef}
          className="box-in"
          rows={1}
          aria-label="Describe your agent"
          placeholder="Summarise my unread email every morning and post it to Slack…"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            e.target.style.height = 'auto';
            e.target.style.height = `${Math.min(e.target.scrollHeight, 180)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <div className="box-bar">
          <div className="box-left">
            <button
              className="box-ico"
              aria-label="Show example tasks"
              aria-pressed={showExamples}
              title="Example tasks"
              onClick={() => setShowExamples((v) => !v)}
            >
              <PlusIcon size={18} strokeWidth={2} />
            </button>
            <div className="modeseg">
              <button aria-pressed="true">Chat</button>
              <button aria-pressed="false" onClick={() => router.push('/create')}>
                Form
              </button>
            </div>
          </div>
          <div className="box-right">
            <button
              className="box-send"
              aria-label="Send"
              disabled={input.trim() === '' || busy}
              onClick={() => void submit()}
            >
              <SendIcon />
            </button>
          </div>
        </div>
      </div>

      {!started || showExamples ? (
        <div className="chips">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => void submit(s)}>
              {s}
            </button>
          ))}
        </div>
      ) : null}

      {draft ? (
        <div className="draftbar">
          <div className="dchips">
            <Chip label="Name" value={draft.name} />
            <Chip label="Model" value={draft.model} />
            <Chip label="Schedule" value={draft.cron} />
            <Chip label="Timezone" value={draft.timezone} />
            <Chip label="Tools" value={draft.tools.length ? draft.tools.join(', ') : 'none yet'} />
          </div>
          <div className="draftact">
            <div className="cprog">
              <div className="bar">
                <i style={{ width: '100%' }} />
              </div>
              <span>Draft ready</span>
            </div>
            <div className="cbtns">
              <span className="badge ok">
                <i />
                Ready
              </span>
              <button className="btn sec" onClick={openInForm}>
                Open in the form
              </button>
              <button className="btn" onClick={() => void create()} disabled={busy}>
                {busy ? 'Creating…' : 'Create agent'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="dchip">
      <span>{label}</span>
      <b className="filled">{value}</b>
    </span>
  );
}
