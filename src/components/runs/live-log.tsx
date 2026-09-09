'use client';

import { useEffect, useRef, useState } from 'react';
import { streamUrl } from '@/lib/api/client';
import { getRunLogs } from '@/lib/api/endpoints';
import { runLogSchema } from '@/lib/api/schemas';
import type { RunLog } from '@/lib/api/schemas';

type Props = {
  runId: number | null;
  /** Follow the live stream; a finished run only needs its stored rows. */
  live: boolean;
  onFinished?: () => void;
};

/**
 * A run's log. Loads the stored rows, then follows the SSE stream if the run is
 * still going — the endpoint replays from the database first, so attaching
 * halfway through misses nothing.
 *
 * Give it `key={runId}` so switching runs remounts it: the line list then
 * starts empty by construction rather than being cleared inside an effect.
 */
export function LiveLog({ runId, live, onFinished }: Props) {
  const [lines, setLines] = useState<RunLog[]>([]);
  const boxRef = useRef<HTMLPreElement | null>(null);

  // The parent passes a useCallback, so it is a real dependency of the
  // subscription rather than something smuggled in through a ref.
  useEffect(() => {
    if (runId === null) return;

    const controller = new AbortController();

    if (!live) {
      getRunLogs(runId, controller.signal)
        .then((result) => {
          if (result.ok) setLines(result.data);
        })
        .catch((e: unknown) => {
          // Unmounting aborts the request; that is not an error to surface.
          if (e instanceof DOMException && e.name === 'AbortError') return;
          throw e;
        });
      return () => controller.abort();
    }

    const source = new EventSource(streamUrl(runId), { withCredentials: true });

    source.onmessage = (event: MessageEvent<string>) => {
      let payload: unknown;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }

      // The stream carries log rows and a terminal marker; anything else is noise.
      const parsed = runLogSchema.safeParse(payload);
      if (parsed.success) {
        setLines((prev) =>
          prev.some((l) => l.seq === parsed.data.seq) ? prev : [...prev, parsed.data],
        );
        return;
      }
      if (
        typeof payload === 'object' &&
        payload !== null &&
        'event' in payload &&
        (payload as { event: unknown }).event === 'done'
      ) {
        source.close();
        onFinished?.();
      }
    };

    // A dropped stream (API restart, proxy timeout) must not freeze the log:
    // fall back to the stored rows, which the endpoint writes as it goes.
    source.onerror = () => {
      source.close();
      getRunLogs(runId, controller.signal)
        .then((result) => {
          if (result.ok) setLines(result.data);
        })
        .catch((e: unknown) => {
          if (e instanceof DOMException && e.name === 'AbortError') return;
          throw e;
        });
    };

    return () => {
      source.close();
      controller.abort();
    };
  }, [runId, live, onFinished]);

  useEffect(() => {
    const box = boxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [lines]);

  if (runId === null) {
    return (
      <pre className="log">
        <code>Pick a run to see its log.</code>
      </pre>
    );
  }

  return (
    <pre className="log" ref={boxRef}>
      <code>
        {lines.length === 0
          ? live
            ? 'Waiting for the worker…'
            : 'No log lines.'
          : lines.map((line, i) => (
              <span key={line.seq}>
                {line.kind === 't' ? (
                  <>
                    <span className="t">{time(line.at)}</span>
                    {'  '}
                    {line.line}
                  </>
                ) : (
                  <span className={line.kind}>
                    {time(line.at)}
                    {'  '}
                    {line.line}
                  </span>
                )}
                {i < lines.length - 1 ? '\n' : null}
              </span>
            ))}
      </code>
    </pre>
  );
}

function time(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return `${at.toLocaleTimeString('en-GB', { hour12: false })}.${String(at.getMilliseconds()).padStart(3, '0')}`;
}
