'use client';

import { useCallback, useEffect, useState } from 'react';
import type { Result } from './client';

/** Mutually exclusive states, so a component cannot render "loaded and erroring". */
export type Load<T> =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: T };

type Options<T> = {
  /** Re-fetch on an interval. Used while something is running. */
  pollMs?: number;
  /**
   * With `pollMs`: keep polling only while this holds for the data just
   * fetched. Must be a stable function (module-level or `useCallback`).
   * Lets the data itself say when to stop, without a second piece of state.
   */
  pollWhile?: (data: T) => boolean;
};

/**
 * Fetch once, then on demand.
 *
 * `fetcher` must be a `useCallback` — it is a real dependency of the effect, so
 * an unstable one refetches every render. Keeping it in the dependency array
 * (rather than hiding it in a ref) is what makes that mistake visible.
 */
export function useLoad<T>(
  fetcher: (signal: AbortSignal) => Promise<Result<T>>,
  options: Options<T> = {},
): { state: Load<T>; reload: () => void } {
  const [state, setState] = useState<Load<T>>({ kind: 'loading' });
  const [nonce, setNonce] = useState(0);
  const { pollMs, pollWhile } = options;

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const again = (result: Result<T> | null) => {
      if (!pollMs || cancelled) return;
      if (pollWhile && !(result?.ok && pollWhile(result.data))) return;
      timer = setTimeout(() => void run(), pollMs);
    };

    const run = async () => {
      let result: Result<T> | null = null;
      try {
        result = await fetcher(controller.signal);
        if (cancelled) return;
        setState(
          result.ok
            ? { kind: 'ready', data: result.data }
            : { kind: 'error', message: result.error.message },
        );
      } catch (e: unknown) {
        // An abort is the component unmounting, not a failure.
        if (e instanceof DOMException && e.name === 'AbortError') return;
        if (!cancelled) {
          setState({ kind: 'error', message: e instanceof Error ? e.message : String(e) });
        }
      }
      again(result);
    };

    void run();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [fetcher, nonce, pollMs, pollWhile]);

  return { state, reload };
}
