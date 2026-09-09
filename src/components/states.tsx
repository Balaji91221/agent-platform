'use client';

import type { ReactNode } from 'react';
import { InfoIcon } from './icons';
import type { Load } from '@/lib/api/use-load';

/** One place that turns a Load<T> into markup, so no page repeats the branches. */
export function Loaded<T>({
  state,
  children,
  skeleton,
}: {
  state: Load<T>;
  children: (data: T) => ReactNode;
  skeleton?: ReactNode;
}) {
  if (state.kind === 'loading') {
    return <>{skeleton ?? <Waiting />}</>;
  }
  if (state.kind === 'error') {
    return <Failed message={state.message} />;
  }
  return <>{children(state.data)}</>;
}

export function Waiting({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="card" aria-busy="true" aria-label={label}>
      <div className="card-body skeleton">
        <span style={{ width: '38%' }} />
        <span style={{ width: '82%' }} />
        <span style={{ width: '64%' }} />
      </div>
    </div>
  );
}

export function Failed({ message }: { message: string }) {
  return (
    <div className="card">
      <div className="card-body">
        <p className="note" style={{ margin: 0 }}>
          <span>
            <b style={{ display: 'block', color: 'var(--err)', marginBottom: 4 }}>
              Could not load this
            </b>
            {message}
          </span>
        </p>
      </div>
    </div>
  );
}

/** An inline message for a failed action (a 402 cap, a 409 lock). */
export function Problem({ message }: { message: string }) {
  return (
    <p
      className="hint"
      style={{ color: 'var(--err)', margin: '10px 0 0', fontWeight: 500 }}
      role="alert"
    >
      {message}
    </p>
  );
}

export function Empty({ message, title }: { message: string; title?: string }) {
  return (
    <div className="empty">
      <span className="eico" aria-hidden="true">
        <InfoIcon size={18} />
      </span>
      {title ? <b>{title}</b> : null}
      <span>{message}</span>
    </div>
  );
}
