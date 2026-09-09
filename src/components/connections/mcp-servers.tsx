'use client';

import { useCallback, useState } from 'react';
import { DocsIcon, GlobeIcon, PlusIcon } from '../icons';
import { Empty, Loaded, Problem } from '../states';
import { CardHead } from '../ui';
import { addMcpServer, deleteMcpServer, listMcpServers, rehandshakeMcpServer } from '@/lib/api/endpoints';
import { mcpToolSchema } from '@/lib/api/schemas';
import { useLoad } from '@/lib/api/use-load';

const AUTH_OPTIONS = ['none', 'bearer', 'oauth'] as const;

/** The tool list is stored as opaque JSON; read the names defensively. */
function toolNames(tools: unknown[]): string[] {
  return tools
    .map((t) => mcpToolSchema.safeParse(t))
    .filter((r) => r.success)
    .map((r) => (r.success ? r.data.name : ''))
    .filter(Boolean);
}

export function McpServers() {
  const servers = useLoad(useCallback((signal) => listMcpServers(signal), []));

  const [url, setUrl] = useState('');
  const [auth, setAuth] = useState<(typeof AUTH_OPTIONS)[number]>('none');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const add = async () => {
    const value = url.trim();
    if (!value) {
      setProblem('Enter the server URL.');
      return;
    }
    setBusy(true);
    setProblem(null);
    const result = await addMcpServer({
      url: value,
      auth_kind: auth,
      token: token.trim() || undefined,
    });
    setBusy(false);
    if (!result.ok) {
      setProblem(result.error.message);
      return;
    }
    // Registering handshakes immediately, so a failure shows in the row itself.
    setUrl('');
    setToken('');
    servers.reload();
  };

  return (
    <div className="card" style={{ marginTop: 24 }}>
      <Loaded state={servers.state}>
        {(rows) => (
          <>
            <CardHead
              title="MCP servers"
              blurb="Paste a server URL and we fetch its tool list. Every tool it exposes becomes available to your agents."
              aside={
                <span className="badge">
                  {rows.filter((s) => s.status === 'ready').length} ready
                </span>
              }
            />
            <div className="card-body">
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'minmax(0,1fr) 140px 160px auto',
                  gap: 14,
                  alignItems: 'end',
                }}
              >
                <div className="fld" style={{ marginBottom: 0 }}>
                  <label htmlFor="mcpurl">Server URL</label>
                  <input
                    className="inp mono"
                    id="mcpurl"
                    type="url"
                    placeholder="https://mcp.example.com/mcp"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        void add();
                      }
                    }}
                  />
                </div>
                <div className="fld" style={{ marginBottom: 0 }}>
                  <label htmlFor="mcpauth">Auth</label>
                  <select
                    className="inp"
                    id="mcpauth"
                    value={auth}
                    onChange={(e) => setAuth(e.target.value as (typeof AUTH_OPTIONS)[number])}
                  >
                    {AUTH_OPTIONS.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="fld" style={{ marginBottom: 0 }}>
                  <label htmlFor="mcptoken">Token</label>
                  <input
                    className="inp"
                    id="mcptoken"
                    type="password"
                    placeholder={auth === 'none' ? 'not needed' : 'bearer token'}
                    disabled={auth === 'none'}
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                  />
                </div>
                <button className="btn" onClick={() => void add()} disabled={busy}>
                  <PlusIcon />
                  {busy ? 'Connecting…' : 'Add server'}
                </button>
              </div>
              {problem ? <Problem message={problem} /> : null}
              <p className="hint" style={{ margin: '10px 0 0' }}>
                Streamable HTTP and SSE endpoints both work. The tool list is cached and refreshed at
                most hourly, never on every run.
              </p>
            </div>

            {rows.length === 0 ? (
              <Empty message="No MCP servers registered yet." />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Server</th>
                    <th>URL</th>
                    <th>Tools</th>
                    <th>Status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((server) => {
                    const names = toolNames(server.tools_json);
                    return (
                      <tr key={server.id}>
                        <td>
                          <div className="tname">
                            <span
                              className="sq"
                              style={{ background: 'linear-gradient(140deg,#1a73e8,#4285f4)' }}
                            >
                              {server.status === 'ready' ? <GlobeIcon /> : <DocsIcon />}
                            </span>
                            <span>
                              <b>{server.name || 'Unnamed server'}</b>
                              <span>{server.auth_kind}</span>
                            </span>
                          </div>
                        </td>
                        <td>
                          <span className="mono" style={{ fontSize: '12.5px', color: 'var(--ink-3)' }}>
                            {server.url}
                          </span>
                        </td>
                        <td>
                          {names.length ? (
                            <div className="apps">
                              {names.slice(0, 2).map((n) => (
                                <span className="app-chip" key={n}>
                                  {n}
                                </span>
                              ))}
                              {names.length > 2 ? (
                                <span className="app-chip">+{names.length - 2}</span>
                              ) : null}
                            </div>
                          ) : (
                            <span className="sub">{server.error ? 'none' : '—'}</span>
                          )}
                        </td>
                        <td>
                          {server.status === 'ready' ? (
                            <span className="badge ok">
                              <i />
                              Ready
                            </span>
                          ) : (
                            <>
                              <span className="badge err">
                                <i />
                                Handshake failed
                              </span>
                              <span className="sub">{(server.error ?? '').slice(0, 48)}</span>
                            </>
                          )}
                        </td>
                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                          <button
                            className="btn sec sm"
                            style={{ marginRight: 8 }}
                            onClick={async () => {
                              await rehandshakeMcpServer(server.id);
                              servers.reload();
                            }}
                          >
                            Retry
                          </button>
                          <button
                            className="btn sec sm"
                            onClick={async () => {
                              await deleteMcpServer(server.id);
                              servers.reload();
                            }}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </>
        )}
      </Loaded>
    </div>
  );
}
