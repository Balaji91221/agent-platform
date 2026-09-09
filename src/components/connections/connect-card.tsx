'use client';

import { useState } from 'react';
import type { ReactNode } from 'react';
import { Problem } from '../states';
import { addConnection, deleteConnection, oauthStart } from '@/lib/api/endpoints';
import type { Connection } from '@/lib/api/schemas';

export type Provider = {
  name: string;
  /** Matches connection.provider on the backend. */
  provider: string;
  sub: string;
  blurb: string;
  background: string;
  icon: ReactNode;
  /** How the real service signs you in. Custom HTTP takes a URL + header. */
  auth: 'oauth' | 'api_key' | 'custom_http';
};

type Props = {
  card: Provider;
  live: Connection | undefined;
  /** False when the backend has no connector for this provider yet. */
  available: boolean;
  onChanged: () => void;
};

type Panel = { kind: 'closed' } | { kind: 'connect' } | { kind: 'manage' };

export function ConnectCard({ card, live, available, onChanged }: Props) {
  const [panel, setPanel] = useState<Panel>({ kind: 'closed' });
  const [secret, setSecret] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [authHeader, setAuthHeader] = useState('Authorization');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const state: 'connected' | 'expired' | 'none' =
    live === undefined ? 'none' : live.status === 'expired' ? 'expired' : 'connected';

  const connect = async () => {
    setBusy(true);
    setProblem(null);
    const result = await addConnection({
      kind: card.auth === 'custom_http' ? 'custom_http' : 'api_key',
      provider: card.provider,
      label: card.name,
      secret,
      base_url: card.auth === 'custom_http' ? baseUrl : undefined,
      auth_header: card.auth === 'custom_http' ? authHeader : undefined,
    });
    setBusy(false);
    if (!result.ok) {
      setProblem(result.error.message);
      return;
    }
    setSecret('');
    setPanel({ kind: 'closed' });
    onChanged();
  };

  /** Real sign-in: the backend builds the provider URL, the browser goes there. */
  const signIn = async () => {
    setBusy(true);
    setProblem(null);
    const result = await oauthStart(card.provider);
    setBusy(false);
    if (!result.ok) {
      setProblem(result.error.message);
      return;
    }
    window.location.assign(result.data.authorize_url);
  };

  const disconnect = async () => {
    if (!live) return;
    setBusy(true);
    const result = await deleteConnection(live.id);
    setBusy(false);
    if (!result.ok) {
      setProblem(result.error.message);
      return;
    }
    setPanel({ kind: 'closed' });
    onChanged();
  };

  return (
    <div className="ccard">
      <div className="top">
        <span className="sq" style={{ background: card.background }}>
          {card.icon}
        </span>
        {state === 'connected' ? (
          <span className="badge ok"><i />Connected</span>
        ) : state === 'expired' ? (
          <span className="badge err"><i />Needs reconnect</span>
        ) : (
          <span className="badge">Not connected</span>
        )}
      </div>
      <div>
        <b>{card.name}</b>
        <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>{live?.label || card.sub}</span>
      </div>
      <p>{card.blurb}</p>

      {!available ? (
        <span className="badge" title="No connector in this build yet">Coming soon</span>
      ) : panel.kind === 'closed' ? (
        state === 'connected' ? (
          <button className="btn sec sm" onClick={() => setPanel({ kind: 'manage' })}>
            Manage
          </button>
        ) : (
          <button className="btn sm" onClick={() => setPanel({ kind: 'connect' })}>
            {state === 'expired' ? 'Reconnect' : 'Connect'}
          </button>
        )
      ) : null}

      {panel.kind === 'connect' ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 4 }}>
          {card.auth === 'oauth' ? (
            <div style={{ display: 'grid', gap: 4 }}>
              <button
                className="btn sm"
                style={{ whiteSpace: 'nowrap', justifySelf: 'start' }}
                disabled={busy}
                onClick={() => void signIn()}
              >
                Sign in with {card.name}
              </button>
              <span className="hint" style={{ margin: 0 }}>or paste a token below</span>
            </div>
          ) : null}
          {card.auth === 'custom_http' ? (
            <>
              <input
                className="inp mono"
                placeholder="https://api.example.com"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                aria-label="Base URL"
              />
              <input
                className="inp mono"
                placeholder="Auth header name"
                value={authHeader}
                onChange={(e) => setAuthHeader(e.target.value)}
                aria-label="Auth header"
              />
            </>
          ) : null}
          <input
            className="inp"
            type="password"
            placeholder={card.auth === 'api_key' ? 'API key' : 'Token or header value'}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            aria-label={`${card.name} secret`}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void connect();
            }}
          />
          {problem ? <Problem message={problem} /> : null}
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn sm" disabled={busy || !secret.trim()} onClick={() => void connect()}>
              {busy ? 'Saving…' : 'Save'}
            </button>
            <button className="btn sec sm" onClick={() => setPanel({ kind: 'closed' })}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {panel.kind === 'manage' && live ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 4 }}>
          <p className="hint" style={{ margin: 0 }}>
            {live.kind} · added {new Date(live.created_at).toLocaleDateString()}. The secret is
            stored encrypted and never shown again.
          </p>
          {problem ? <Problem message={problem} /> : null}
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              className="btn sm"
              style={{ background: 'var(--err)' }}
              disabled={busy}
              onClick={() => void disconnect()}
            >
              Disconnect
            </button>
            <button className="btn sec sm" onClick={() => setPanel({ kind: 'closed' })}>
              Close
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
