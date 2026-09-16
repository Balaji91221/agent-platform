'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useState } from 'react';
import { A2ACard } from './a2a-card';
import { ScheduleCard } from './schedule-card';
import { ToolsCard } from './tools-card';
import { Loaded, Problem } from '../states';
import { CardHead, PageHead } from '../ui';
import { createAgent, listConnections, listModels, listTools, updateAgent } from '@/lib/api/endpoints';
import type { Model } from '@/lib/api/schemas';
import { useLoad } from '@/lib/api/use-load';
import { FREQUENCIES, cronFor, presetFor } from '@/lib/schedule';

/** Everything the form starts from. Both "new" and "edit" reduce to this. */
export type FormSeed = {
  name: string;
  description: string;
  system_prompt: string;
  user_prompt: string;
  model: string;
  tools: { tool_name: string; can_write: boolean }[];
  schedule: { cron: string; timezone: string; is_paused?: boolean } | null;
  /** Reachable by other agents over A2A. Off unless switched on here. */
  a2a_enabled: boolean;
};

export const DEFAULT_SEED: FormSeed = {
  name: 'Morning inbox digest',
  description: 'Summarises unread mail into #daily',
  system_prompt:
    'You are an assistant that triages an inbox for a busy engineering manager.\n\n' +
    'Be concise and factual. Never invent a sender or a subject line.',
  user_prompt:
    'Read every unread message received since {{last_run}}. Group them by sender.\n\n' +
    'Write at most six bullets, newest first. Post the result to #daily.',
  model: 'nemotron-3-super',
  tools: [],
  schedule: { cron: '0 9 * * *', timezone: 'Asia/Kolkata' },
  a2a_enabled: false,
};

type Props = {
  seed: FormSeed;
  /** Set when editing; the save becomes a PATCH to this agent. */
  editingId?: number;
};

export function AgentForm({ seed, editingId }: Props) {
  const router = useRouter();
  const editing = editingId !== undefined;

  const models = useLoad(useCallback((signal) => listModels(signal), []));
  const tools = useLoad(useCallback((signal) => listTools(signal), []));
  const connections = useLoad(useCallback((signal) => listConnections(signal), []));
  const connected =
    connections.state.kind === 'ready'
      ? new Set(connections.state.data.filter((c) => c.status === 'connected').map((c) => c.provider))
      : undefined;

  const [name, setName] = useState(seed.name);
  const [model, setModel] = useState(seed.model);
  const [description, setDescription] = useState(seed.description);
  const [system, setSystem] = useState(seed.system_prompt);
  const [userPrompt, setUserPrompt] = useState(seed.user_prompt);
  const [enabled, setEnabled] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(seed.tools.map((t) => [t.tool_name, true])),
  );
  const [writable, setWritable] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(seed.tools.map((t) => [t.tool_name, t.can_write])),
  );
  // A daily/weekday/weekly cron seeds the preset + time picker; anything else
  // is kept verbatim as a custom rule.
  const preset = seed.schedule ? presetFor(seed.schedule.cron) : null;
  const [freq, setFreq] = useState(preset ? preset.freq : 2);
  const [customCron, setCustomCron] = useState(
    seed.schedule && !preset ? seed.schedule.cron : '',
  );
  const [at, setAt] = useState(preset ? preset.at : '09:00');
  const [tz, setTz] = useState(seed.schedule?.timezone ?? 'Asia/Kolkata');
  const [scheduled, setScheduled] = useState(seed.schedule !== null);
  const [a2a, setA2a] = useState(seed.a2a_enabled);
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const catalogue = tools.state.kind === 'ready' ? tools.state.data : [];
  const enabledTools = catalogue.filter((t) => enabled[t.name]);
  const cron = customCron.trim() || cronFor(freq, at);

  const save = async () => {
    setSaving(true);
    setProblem(null);
    const body = {
      name,
      description,
      system_prompt: system,
      user_prompt: userPrompt,
      model,
      tools: enabledTools.map((t) => ({
        tool_name: t.name,
        can_write: t.writes ? !!writable[t.name] : false,
      })),
      // Editing must not silently resume a paused schedule: keep the seed's
      // state while the schedule stays on; a schedule switched on here starts active.
      schedule: scheduled
        ? { cron, timezone: tz, is_paused: seed.schedule?.is_paused ?? false }
        : null,
      a2a_enabled: a2a,
    };
    const result = editing ? await updateAgent(editingId, body) : await createAgent(body);
    setSaving(false);
    if (!result.ok) {
      setProblem(result.error.message);
      return;
    }
    router.push(`/agents/${result.data.id}`);
  };

  const canSave = !saving && name.trim() !== '';

  return (
    <>
      <PageHead
        title={editing ? `Edit ${seed.name}` : 'New agent'}
        blurb={
          editing
            ? 'Changes apply to the next run. A run already in progress keeps the old prompts.'
            : 'Write the instructions, pick the tools it may call, and choose when it runs.'
        }
        actions={
          <div style={{ display: 'flex', gap: 9 }}>
            <Link className="btn sec" href={editing ? `/agents/${editingId}` : '/agents'}>
              Cancel
            </Link>
            <button className="btn" onClick={() => void save()} disabled={!canSave}>
              {saving ? 'Saving…' : editing ? 'Save changes' : 'Create agent'}
            </button>
          </div>
        }
      />

      {problem ? <Problem message={problem} /> : null}

      <div className="form-grid">
        <div className="stack">
          <div className="card">
            <CardHead title="Basics" />
            <div className="card-body">
              <div className="row2">
                <div className="fld">
                  <label htmlFor="an">Name</label>
                  <input className="inp" id="an" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="fld">
                  <label htmlFor="am">Model</label>
                  <Loaded
                    state={models.state}
                    skeleton={<select className="inp" disabled><option>Loading…</option></select>}
                  >
                    {(list) => <ModelSelect list={list} value={model} onChange={setModel} />}
                  </Loaded>
                </div>
              </div>
              <div className="fld">
                <label htmlFor="ad">What it does</label>
                <p className="hint">Shown in the agent list. One line is enough.</p>
                <input className="inp" id="ad" value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>
            </div>
          </div>

          <div className="card">
            <CardHead
              title="System prompt"
              blurb="Who the agent is. Sent on every run, before anything else."
              aside={<span className="badge">Always sent</span>}
            />
            <div className="card-body">
              <div className="fld">
                <textarea className="ta" rows={7} value={system} onChange={(e) => setSystem(e.target.value)} />
                <div className="charct">
                  <span>{system.length.toLocaleString()}</span> characters
                </div>
              </div>
            </div>
          </div>

          <div className="card">
            <CardHead title="User prompt" blurb="The task itself. Runs after the system prompt, every time." />
            <div className="card-body">
              <div className="fld">
                <textarea className="ta" rows={6} value={userPrompt} onChange={(e) => setUserPrompt(e.target.value)} />
                <div className="charct">
                  <span>{userPrompt.length.toLocaleString()}</span> characters
                </div>
              </div>
              <div className="cronbox">
                <span style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--ink-2)' }}>
                  Variables you can use
                </span>
                <span>
                  <span className="mono">{'{{last_run}}'}</span> <span className="mono">{'{{now}}'}</span>{' '}
                  <span className="mono">{'{{agent_name}}'}</span>
                </span>
              </div>
            </div>
          </div>

          <Loaded state={tools.state}>
            {(list) => (
              <ToolsCard
                catalogue={list}
                enabled={enabled}
                writable={writable}
                connected={connected}
                onToggle={(n) => setEnabled((p) => ({ ...p, [n]: !p[n] }))}
                onToggleWrite={(n) => setWritable((p) => ({ ...p, [n]: !p[n] }))}
              />
            )}
          </Loaded>

          <ScheduleCard
            freq={freq}
            at={at}
            tz={tz}
            customCron={customCron}
            enabled={scheduled}
            onFreq={(i) => {
              setFreq(i);
              setCustomCron('');
            }}
            onCustomCron={setCustomCron}
            onAt={setAt}
            onTz={setTz}
            onToggle={() => setScheduled((s) => !s)}
          />

          <A2ACard enabled={a2a} onToggle={() => setA2a((v) => !v)} />
        </div>

        <div className="stack" style={{ position: 'sticky', top: 78 }}>
          <div className="preview">
            <h4>Summary</h4>
            <div className="pv-row"><span>Model</span><b>{model}</b></div>
            <div className="pv-row">
              <span>Schedule</span>
              <b>{scheduled ? (customCron.trim() ? cron : `${FREQUENCIES[freq].label}, ${at}`) : 'Manual only'}</b>
            </div>
            <div className="pv-row">
              <span>Tools enabled</span>
              <b>{enabledTools.length} of {catalogue.length || '…'}</b>
            </div>
            <div className="pv-row">
              <span>Write access</span>
              <b>{enabledTools.filter((t) => t.writes && writable[t.name]).length} tools</b>
            </div>
            <div className="pv-row">
              <span>A2A</span>
              <b>{a2a ? 'Other agents can call it' : 'Off'}</b>
            </div>
            <button
              className="btn"
              style={{ width: '100%', justifyContent: 'center', marginTop: 14 }}
              onClick={() => void save()}
              disabled={!canSave}
            >
              {saving ? 'Saving…' : editing ? 'Save changes' : 'Create agent'}
            </button>
          </div>
          <div className="card">
            <div className="card-body" style={{ fontSize: '12.5px', color: 'var(--ink-2)', fontWeight: 500 }}>
              <b style={{ display: 'block', color: 'var(--ink)', fontSize: 13, marginBottom: 6 }}>
                Before you turn it on
              </b>
              Run it once by hand and read the log. A scheduled agent with a write tool enabled will act
              on real data whether or not the prompt was right.
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function ModelSelect({ list, value, onChange }: { list: Model[]; value: string; onChange: (v: string) => void }) {
  const groups = new Map<string, Model[]>();
  for (const m of list) {
    const bucket = groups.get(m.provider) ?? [];
    bucket.push(m);
    groups.set(m.provider, bucket);
  }
  return (
    <select className="inp" id="am" value={value} onChange={(e) => onChange(e.target.value)}>
      {[...groups.entries()].map(([provider, models]) => (
        <optgroup key={provider} label={provider === 'nvidia' ? 'Open models (NVIDIA)' : 'Anthropic'}>
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
              {m.vision ? ' · vision' : ''}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
