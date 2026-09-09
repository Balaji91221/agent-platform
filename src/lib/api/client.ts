/**
 * The one place the browser talks to the backend.
 *
 * Failure is in the return type, not thrown: a 402 cap or a 409 lock is an
 * ordinary answer the UI has to render, not an exception. Every response is
 * parsed by a zod schema before it reaches a component.
 */
import type { ZodType } from 'zod';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/** A 401 anywhere means the session is gone; the login page is the only useful place. */
function sendToLogin(): void {
  if (typeof window === 'undefined') return;
  if (window.location.pathname === '/login') return;
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- full reload drops stale state
  window.location.assign('/login');
}

export type ApiError = {
  status: number;
  code: string;
  message: string;
};

export type Result<T> = { ok: true; data: T } | { ok: false; error: ApiError };

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
};

/** The backend's error envelope; anything else is reported as-is. */
function readError(status: number, payload: unknown): ApiError {
  if (
    typeof payload === 'object' &&
    payload !== null &&
    'error' in payload &&
    typeof (payload as { error: unknown }).error === 'object'
  ) {
    const inner = (payload as { error: Record<string, unknown> }).error;
    return {
      status,
      code: typeof inner.code === 'string' ? inner.code : 'ERROR',
      message: typeof inner.message === 'string' ? inner.message : `Request failed (${status})`,
    };
  }
  return { status, code: 'ERROR', message: `Request failed (${status})` };
}

export async function request<T>(
  path: string,
  schema: ZodType<T>,
  options: RequestOptions = {},
): Promise<Result<T>> {
  const { method = 'GET', body, signal } = options;

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      signal,
      credentials: 'include',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    return {
      ok: false,
      error: {
        status: 0,
        code: 'OFFLINE',
        message: `Cannot reach the backend at ${BASE_URL}. Is it running?`,
      },
    };
  }

  if (response.status === 204) {
    const parsed = schema.safeParse(null);
    return parsed.success
      ? { ok: true, data: parsed.data }
      : { ok: true, data: undefined as T };
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (response.status === 401) {
    sendToLogin();
  }
  if (!response.ok) {
    return { ok: false, error: readError(response.status, payload) };
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    return {
      ok: false,
      error: {
        status: response.status,
        code: 'BAD_SHAPE',
        message: `${path} returned an unexpected shape: ${parsed.error.issues
          .slice(0, 2)
          .map((i) => `${i.path.join('.')} ${i.message}`)
          .join('; ')}`,
      },
    };
  }

  return { ok: true, data: parsed.data };
}

/** The SSE URL for a run's live log. */
export function streamUrl(runId: number): string {
  return `${BASE_URL}/runs/${runId}/stream`;
}

export { BASE_URL };
