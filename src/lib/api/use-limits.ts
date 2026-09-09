import { useCallback } from 'react';
import { getHealth } from './endpoints';
import type { Limits } from './schemas';
import { useLoad } from './use-load';

/** Matches backend/app/config.py defaults; replaced by /health as soon as it answers. */
const DEFAULTS: Limits = {
  max_attempts: 3,
  retry_backoff_seconds: [1, 2, 4],
  run_timeout_seconds: 300,
  max_tool_calls_per_run: 20,
  tool_call_timeout_seconds: 30,
  max_agents_per_user: 5,
};

/** The run caps the UI quotes, read from the backend instead of hard-coded. */
export function useLimits(): Limits {
  const health = useLoad(useCallback((signal) => getHealth(signal), []));
  return health.state.kind === 'ready' ? health.state.data.limits : DEFAULTS;
}

export function minutes(seconds: number): string {
  return seconds % 60 === 0 ? `${seconds / 60} minute${seconds === 60 ? '' : 's'}` : `${seconds}s`;
}
