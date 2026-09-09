'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useCallback } from 'react';
import { AgentIcon } from '@/components/icons';
import { Empty, Loaded, Problem } from '@/components/states';
import { CardHead, PageHead } from '@/components/ui';
import { listAgents } from '@/lib/api/endpoints';
import { useLoad } from '@/lib/api/use-load';
import { useTeam } from '@/lib/team-store';

export default function MatePage() {
  return (
    <Suspense fallback={null}>
      <AddTeammate />
    </Suspense>
  );
}

function AddTeammate() {
  const router = useRouter();
  const params = useSearchParams();
  const { team, draft, problem, setDraft, addMate } = useTeam();

  const agents = useLoad(useCallback((signal) => listAgents(signal), []));

  // "Add to team" from the agents table arrives with ?agent=. Derived, so no
  // effect writes state during the first render.
  const preselect = params.get('agent');
  const chosenId = draft.agentId ?? (preselect ? Number(preselect) : null);

  const chosenAgent =
    agents.state.kind === 'ready' ? agents.state.data.find((a) => a.id === chosenId) : undefined;
  // Defaults come from the agent; typing replaces them. Nothing is copied into state.
  const title = draft.title || chosenAgent?.description || chosenAgent?.name || '';
  const description = draft.description || chosenAgent?.description || '';

  const roster = team.kind === 'ready' ? team.data.teammates : [];
  const mateFor = (agentId: number) => roster.find((m) => m.agent_id === agentId);
  const lead = roster.find((m) => m.is_lead);

  const canSave = chosenId !== null && draft.name.trim() !== '' && title.trim() !== '';

  const save = async () => {
    if (chosenId === null) return;
    const ok = await addMate({
      agentId: chosenId,
      name: draft.name.trim(),
      title: title.trim(),
      description: description.trim(),
      lead: draft.lead,
    });
    if (ok) router.push('/team');
  };

  const chosenName = chosenAgent?.name;

  return (
    <>
      <PageHead
        title="Add teammate"
        blurb="A teammate is one of your agents given a name and a job title. The title is what the lead reads when it decides who to hand work to, so keep it specific."
        actions={
          <div style={{ display: 'flex', gap: 9 }}>
            <Link className="btn sec" href="/team">
              Cancel
            </Link>
            <button className="btn" disabled={!canSave} onClick={() => void save()}>
              Add to team
            </button>
          </div>
        }
      />

      {problem ? <Problem message={problem} /> : null}

      <div className="teamgrid">
        <div className="card">
          <CardHead title="Pick an agent" blurb="Agents you have already built" />
          <Loaded state={agents.state}>
            {(list) =>
              list.length === 0 ? (
                <Empty message="No agents yet. Build one first." />
              ) : (
                <ul className="mates">
                  {list.map((agent) => {
                    const already = mateFor(agent.id);
                    return (
                      <li key={agent.id}>
                        <button
                          className="pick"
                          disabled={!!already}
                          aria-pressed={chosenId === agent.id}
                          onClick={() => setDraft({ agentId: agent.id })}
                        >
                          <span
                            className="sq"
                            style={{ background: 'linear-gradient(140deg,#9aa0a6,#bdc1c6)' }}
                          >
                            <AgentIcon size={15} />
                          </span>
                          <span className="pb">
                            <b>{agent.name}</b>
                            <span className="d">{agent.description || agent.model}</span>
                          </span>
                          <span className="act">
                            {already ? `Added as ${already.display_name}` : 'Add'}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )
            }
          </Loaded>
          <div
            className="card-body"
            style={{ borderTop: '1px solid var(--outline-2)', padding: '16px 20px' }}
          >
            <Link className="btn sec sm" href="/create" style={{ width: '100%', justifyContent: 'center' }}>
              Build a new agent instead
            </Link>
          </div>
        </div>

        <div className="card">
          <CardHead
            title="Give it a name and a job"
            blurb={chosenName ? `From your agent: ${chosenName}` : 'Pick an agent on the left to start'}
          />
          <div className="card-body">
            <div className="fld">
              <label htmlFor="m-name">Name</label>
              <input
                className="inp"
                id="m-name"
                placeholder="Ravi"
                value={draft.name}
                onChange={(e) => setDraft({ name: e.target.value })}
              />
              <p className="hint" style={{ margin: '8px 0 0' }}>
                What you call it in the thread, and what you type after @ to reach it directly.
              </p>
            </div>

            <div className="fld">
              <label htmlFor="m-title">Job title</label>
              <input
                className="inp"
                id="m-title"
                placeholder="Billing analyst"
                value={title}
                onChange={(e) => setDraft({ title: e.target.value })}
              />
              <p className="hint" style={{ margin: '8px 0 0' }}>
                The lead routes work by matching the request against these titles.
              </p>
            </div>

            <div className="fld">
              <label htmlFor="m-desc">What it does</label>
              <textarea
                className="inp"
                id="m-desc"
                rows={3}
                style={{ resize: 'vertical', lineHeight: 1.6, minHeight: 86 }}
                placeholder="Pulls invoices from Stripe, checks them against the contract, and flags anything that does not match."
                value={description}
                onChange={(e) => setDraft({ description: e.target.value })}
              />
            </div>

            <div className="fld" style={{ marginBottom: 0 }}>
              <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  style={{ margin: '2px 0 0' }}
                  checked={draft.lead}
                  onChange={(e) => setDraft({ lead: e.target.checked })}
                />
                <span>
                  <span style={{ display: 'block' }}>Make this the team lead</span>
                  <span className="hint" style={{ display: 'block', marginTop: 4 }}>
                    {lead
                      ? `The lead owns every message that is not @mentioned. ${lead.display_name} has it now, and ticking this takes it over.`
                      : 'The lead owns every message that is not @mentioned. Nobody has it, so messages to the room go unclaimed.'}
                  </span>
                </span>
              </label>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
