'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useState } from 'react';
import { PlusIcon } from '@/components/icons';
import { Empty, Loaded, Problem } from '@/components/states';
import { PageHead } from '@/components/ui';
import { deleteAgent, getTeam, listAgents } from '@/lib/api/endpoints';
import { useLoad } from '@/lib/api/use-load';
import { appsFor, lookFor } from '@/lib/agent-visuals';

export default function AgentsPage() {
  const router = useRouter();
  const [problem, setProblem] = useState<string | null>(null);
  // The row whose delete is awaiting a second click.
  const [armed, setArmed] = useState<number | null>(null);

  const agents = useLoad(useCallback((signal) => listAgents(signal), []));
  const team = useLoad(useCallback((signal) => getTeam(signal), []));

  const onTeam = (agentId: number) =>
    team.state.kind === 'ready'
      ? team.state.data.teammates.find((m) => m.agent_id === agentId)
      : undefined;

  const remove = async (id: number, name: string) => {
    const result = await deleteAgent(id);
    if (!result.ok) {
      setProblem(`Could not delete ${name}: ${result.error.message}`);
      return;
    }
    setProblem(null);
    setArmed(null);
    agents.reload();
    team.reload();
  };

  return (
    <>
      <PageHead
        title="Agents"
        blurb="An agent is a saved set of instructions, the apps it may reach, and when it should run."
        actions={
          <Link className="btn" href="/create">
            <PlusIcon />
            New agent
          </Link>
        }
      />

      {problem ? <Problem message={problem} /> : null}

      <Loaded state={agents.state}>
        {(rows) => (
          <div className="card">
            {rows.length === 0 ? (
              <Empty message="No agents yet. Create one, or describe it in chat." />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th>Schedule</th>
                    <th>Next run</th>
                    <th>Connections</th>
                    <th>Status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((agent) => {
                    const look = lookFor(agent.name);
                    const apps = appsFor(agent.tools.map((t) => t.tool_name));
                    const mate = onTeam(agent.id);
                    return (
                      <tr key={agent.id}>
                        <td>
                          <div className="tname">
                            <span className="sq" style={{ background: look.background }}>
                              {look.icon}
                            </span>
                            <span>
                              <Link className="link" href={`/agents/${agent.id}`}>
                                {agent.name}
                              </Link>
                              <span>{agent.description || agent.model}</span>
                            </span>
                          </div>
                        </td>
                        <td>
                          {agent.schedule ? (
                            <>
                              <span className="mono">{agent.schedule.cron}</span>
                              <span className="sub">{agent.schedule.words}</span>
                            </>
                          ) : (
                            <span className="sub">No schedule</span>
                          )}
                        </td>
                        <td style={{ fontWeight: 500 }}>
                          {!agent.schedule ? (
                            '—'
                          ) : agent.schedule.is_paused ? (
                            <span className="badge">Paused</span>
                          ) : (
                            agent.schedule.next_runs[0] ?? '—'
                          )}
                        </td>
                        <td>
                          <div className="apps">
                            {apps.length === 0 ? (
                              <span className="sub">None</span>
                            ) : (
                              apps.map((app) => (
                                <span className="app-chip" key={app.name}>
                                  <s style={{ background: app.colour }} />
                                  {app.name}
                                </span>
                              ))
                            )}
                          </div>
                        </td>
                        <td>
                          {agent.is_running ? (
                            <span className="badge run">
                              <i />
                              Running
                            </span>
                          ) : (
                            <span className="badge ok">
                              <i />
                              Idle
                            </span>
                          )}
                          <span className="sub">{agent.model}</span>
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          {mate ? (
                            <button className="badge" disabled style={{ marginRight: 8 }}>
                              On the team as {mate.display_name}
                            </button>
                          ) : (
                            <button
                              className="btn sec sm"
                              style={{ marginRight: 8 }}
                              onClick={() => router.push(`/mate?agent=${agent.id}`)}
                            >
                              Add to team
                            </button>
                          )}
                          {armed === agent.id ? (
                            <>
                              <button
                                className="btn sm"
                                style={{ background: 'var(--err)', marginRight: 6 }}
                                onClick={() => remove(agent.id, agent.name)}
                              >
                                Confirm delete
                              </button>
                              <button className="btn sec sm" onClick={() => setArmed(null)}>
                                Keep
                              </button>
                            </>
                          ) : (
                            <button
                              className="btn sec sm"
                              disabled={agent.is_running}
                              title={agent.is_running ? 'Wait for the run to finish' : undefined}
                              onClick={() => setArmed(agent.id)}
                            >
                              Delete
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}
      </Loaded>
    </>
  );
}
