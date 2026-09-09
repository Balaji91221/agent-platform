'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { Problem } from '@/components/states';
import { loginUrl } from '@/lib/api/endpoints';

function LoginError() {
  const params = useSearchParams();
  const error = params.get('error');
  return error ? <Problem message={`Sign-in failed: ${error}`} /> : null;
}

export default function LoginPage() {
  return (
    <div className="login-wrap">
      <div className="login-split">
        <aside className="login-side">
          <div className="logo-row">
            <span className="mark">R</span>
            Relay
          </div>
          <div>
            <h2>Agents that work through your real accounts.</h2>
            <p>
              Describe a job in plain words. Relay writes the prompts, picks a schedule, and runs it
              against Gmail, Slack, and Sheets as you.
            </p>
          </div>
          <ul>
            <li>
              <i>1</i>
              <span>Build an agent in chat, or fill in a short form.</span>
            </li>
            <li>
              <i>2</i>
              <span>Put agents on a team; the lead routes each message to the right one.</span>
            </li>
            <li>
              <i>3</i>
              <span>Watch every run live, with a log line for each step.</span>
            </li>
          </ul>
        </aside>
        <div className="login-card">
          <h1>Sign in</h1>
          <p>Agents that act through your real accounts. Sign in with the Google account you want them to work as.</p>
          <a className="btn google" href={loginUrl()}>
            <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
              <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.6 2.6 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.3l7.8 6C12.3 13.6 17.7 9.5 24 9.5z" />
              <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4 7.1-10 7.1-17.5z" />
              <path fill="#FBBC05" d="M10.4 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.8-4.7l-7.8-6A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.7l7.8-6z" />
              <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.9 2.3-8.4 2.3-6.3 0-11.7-4.1-13.6-9.9l-7.8 6C6.5 42.6 14.6 48 24 48z" />
            </svg>
            Continue with Google
          </a>
          <Suspense fallback={null}>
            <LoginError />
          </Suspense>
          <span className="hint">One sign-in also connects Gmail and Google Sheets for your agents. Untick either on Google&rsquo;s consent screen to leave it out.</span>
        </div>
      </div>
    </div>
  );
}
