'use client';

import { AlertCircleIcon, RefreshIcon } from './icons';

/**
 * Shown when the browser could not reach the backend at all. Deliberately not
 * the sign-in page: the user is not signed out, and the sign-in button would
 * fail for the same reason.
 */
export function Offline({ message }: { message: string }) {
  return (
    <div className="offline">
      <span className="oico" aria-hidden="true">
        <AlertCircleIcon size={22} />
      </span>
      <h1>Relay cannot reach its backend</h1>
      <p>{message}</p>
      <p className="osub">
        You are still signed in. Start the backend, then try again.
      </p>
      <pre>cd backend &amp;&amp; ./scripts/dev.sh</pre>
      <button className="btn" onClick={() => window.location.reload()}>
        <RefreshIcon />
        Try again
      </button>
    </div>
  );
}
