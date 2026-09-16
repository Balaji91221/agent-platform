'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Empty, Loaded } from '../states';
import { CardHead } from '../ui';
import { stateOf, useTeam } from '@/lib/team-store';
import type { TeamMessage, Teammate } from '@/lib/api/schemas';

const initials = (n: string) => n.slice(0, 2).toUpperCase();

const STATE_LABEL = { idle: 'Idle', working: 'Working…', blocked: 'Needs you' } as const;

type EditForm = { id: number; name: string; title: string; description: string; colour: string };

/** Same palette new teammates are dealt from, so a hand-picked colour still fits. */
const SWATCHES = ['#2d4470', '#1a6b3c', '#8a5a00', '#611f69', '#0b6e7f', '#a3231c', '#3b6fd6', '#5e6ad2'];

export function Roster({ onMention }: { onMention: (name: string) => void }) {
  const { team, thread, makeLead, standDown, remove, edit } = useTeam();
  const messages: TeamMessage[] = thread.kind === 'ready' ? thread.data : [];
  const [form, setForm] = useState<EditForm | null>(null);
  const [saving, setSaving] = useState(false);

  const startEdit = (mate: Teammate) =>
    setForm({
      id: mate.id,
      name: mate.display_name,
      title: mate.job_title,
      description: mate.description,
      colour: mate.colour,
    });

  const saveEdit = async () => {
    if (!form) return;
    setSaving(true);
    const ok = await edit(form.id, {
      display_name: form.name.trim(),
      job_title: form.title.trim(),
      description: form.description.trim(),
      colour: form.colour,
    });
    setSaving(false);
    if (ok) setForm(null);
  };

  return (
    <Loaded state={team}>
      {(data) => {
        const mates = data.teammates;
        const states = mates.map((m) => stateOf(m, messages));
        const busy = mates.filter((_, i) => states[i] === 'working');
        const stuck = mates.filter((_, i) => states[i] === 'blocked');

        const status = !mates.length
          ? 'Nobody on the team'
          : stuck.length
            ? `${stuck[0].display_name} is waiting on you`
            : busy.length
              ? `${busy.map((m) => m.display_name).join(' and ')}${busy.length > 1 ? ' are' : ' is'} working`
              : 'Everyone idle';

        return (
          <div className="card roster">
            <CardHead title="Who's on the team" blurb={status} />

            {!mates.length ? (
              <p className="nolead">
                <b>No teammates yet.</b> Add one, then make it the lead so messages to the room have
                an owner.
              </p>
            ) : data.lead_teammate_id === null ? (
              <p className="nolead">
                <b>No lead set.</b> Anything you send the room has nobody to claim it. Pick a lead,
                or @mention a teammate directly.
              </p>
            ) : null}

            {mates.length === 0 ? (
              <Empty message="Add a teammate to get started." />
            ) : (
              <ul className="mates">
                {mates.map((mate, i) =>
                  form && form.id === mate.id ? (
                    <li key={mate.id}>
                      <div className="mate-form">
                        <input
                          className="inp"
                          aria-label="Name"
                          value={form.name}
                          onChange={(e) => setForm({ ...form, name: e.target.value })}
                        />
                        <input
                          className="inp"
                          aria-label="Job title"
                          value={form.title}
                          onChange={(e) => setForm({ ...form, title: e.target.value })}
                        />
                        <textarea
                          className="inp"
                          aria-label="What it does"
                          rows={2}
                          value={form.description}
                          onChange={(e) => setForm({ ...form, description: e.target.value })}
                        />
                        <div className="swatches" role="radiogroup" aria-label="Colour">
                          {SWATCHES.map((c) => (
                            <button
                              key={c}
                              type="button"
                              role="radio"
                              aria-checked={form.colour === c}
                              aria-label={c}
                              style={{ background: c }}
                              onClick={() => setForm({ ...form, colour: c })}
                            />
                          ))}
                        </div>
                        <div className="acts">
                          <button
                            className="btn sm"
                            disabled={saving || !form.name.trim() || !form.title.trim()}
                            onClick={() => void saveEdit()}
                          >
                            {saving ? 'Saving…' : 'Save'}
                          </button>
                          <button className="btn sec sm" onClick={() => setForm(null)}>
                            Cancel
                          </button>
                        </div>
                      </div>
                    </li>
                  ) : (
                    <li key={mate.id}>
                      <button
                        className="mate"
                        data-state={states[i]}
                        onClick={() => {
                          if (!mate.is_lead) onMention(mate.display_name);
                        }}
                      >
                        <span className="ava" style={{ background: mate.colour }}>
                          {initials(mate.display_name)}
                          <s />
                        </span>
                        <span className="who-b">
                          <span className="nm">
                            <b>
                              {mate.display_name}
                              {mate.is_lead ? <span className="lead-tag">lead</span> : null}
                            </b>
                            <span className="state">{STATE_LABEL[states[i]]}</span>
                          </span>
                          <span className="role">{mate.job_title}</span>
                          <span className="job">{mate.description}</span>
                          <span className="src">{mate.agent_name}</span>
                        </span>
                      </button>
                      <div className="mate-acts">
                        {mate.is_lead ? (
                          <>
                            <button disabled>Lead</button>
                            <button onClick={() => void standDown()}>Step down</button>
                          </>
                        ) : (
                          <button onClick={() => void makeLead(mate.id)}>Make lead</button>
                        )}
                        <button onClick={() => startEdit(mate)}>Edit</button>
                        <Link href={`/agents/${mate.agent_id}`}>Open</Link>
                        <button className="danger" onClick={() => void remove(mate.id)}>
                          Remove
                        </button>
                      </div>
                    </li>
                  ),
                )}
              </ul>
            )}

            <div
              className="card-body"
              style={{ borderTop: '1px solid var(--outline-2)', padding: '16px 20px' }}
            >
              <p style={{ margin: 0, fontSize: '12.5px', color: 'var(--ink-3)', lineHeight: 1.55 }}>
                Connections are shared. Gmail is authorised once and every teammate can reach it, so
                keep the team small and give each one a narrow job.
              </p>
            </div>
          </div>
        );
      }}
    </Loaded>
  );
}
