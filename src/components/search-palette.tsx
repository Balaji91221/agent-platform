'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { listAgents } from '@/lib/api/endpoints';
import { useLoad } from '@/lib/api/use-load';

type Props = { open: boolean; onClose: () => void };

/** Find an agent by name or description and jump to it. Enter opens the first match. */
export function SearchPalette({ open, onClose }: Props) {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement | null>(null);
  const agents = useLoad(useCallback((signal) => listAgents(signal), []));

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  if (!open) return null;

  const q = query.trim().toLowerCase();
  const rows = agents.state.kind === 'ready' ? agents.state.data : [];
  const matches = (q ? rows.filter((a) => `${a.name} ${a.description}`.toLowerCase().includes(q)) : rows).slice(0, 8);

  const go = (id: number) => {
    onClose();
    setQuery('');
    router.push(`/agents/${id}`);
  };

  return (
    <div className="palette-backdrop" onClick={onClose} role="presentation">
      <div className="palette" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Search agents">
        <input
          ref={inputRef}
          className="inp"
          placeholder="Search agents…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onClose();
            if (e.key === 'Enter' && matches[0]) go(matches[0].id);
          }}
        />
        <ul>
          {matches.map((a) => (
            <li key={a.id}>
              <button onClick={() => go(a.id)}>
                <b>{a.name}</b>
                <span>{a.description || (a.schedule ? a.schedule.cron : 'manual only')}</span>
              </button>
            </li>
          ))}
          {matches.length === 0 ? (
            <li className="empty">
              {agents.state.kind === 'ready' ? 'No agent matches.' : 'Loading…'}{' '}
              <button onClick={() => { onClose(); router.push('/chat'); }}>Build one with chat</button>
            </li>
          ) : null}
        </ul>
      </div>
    </div>
  );
}
