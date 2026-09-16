'use client';

import { usePathname, useRouter } from 'next/navigation';
import { createContext, useCallback, useContext, useEffect } from 'react';
import type { ReactNode } from 'react';
import { getMe, logout as logoutRequest } from '@/lib/api/endpoints';
import { useLoad } from '@/lib/api/use-load';
import type { Me } from '@/lib/api/schemas';

type AuthState =
  | { kind: 'loading' }
  | { kind: 'anonymous' }
  /** The backend did not answer at all. Sending the user to sign in would lie. */
  | { kind: 'offline'; message: string }
  | { kind: 'signed-in'; me: Me };

type AuthValue = { state: AuthState; logout: () => Promise<void> };

const AuthContext = createContext<AuthValue | null>(null);

/**
 * Who is signed in, from GET /auth/me. Anonymous on any page but /login means
 * the session is gone, so the browser goes to /login; the API client does the
 * same on any 401 it meets later. A request that never reached the backend is
 * kept separate: bouncing to sign-in there sends the user to a button that
 * cannot work either, and hides the real fault.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const me = useLoad(useCallback((signal) => getMe(signal), []));

  const state: AuthState =
    me.state.kind === 'ready'
      ? { kind: 'signed-in', me: me.state.data }
      : me.state.kind === 'error' && me.state.code === 'OFFLINE'
        ? { kind: 'offline', message: me.state.message }
        : me.state.kind === 'error'
          ? { kind: 'anonymous' }
          : { kind: 'loading' };

  useEffect(() => {
    if (state.kind === 'anonymous' && pathname !== '/login') router.replace('/login');
    if (state.kind === 'signed-in' && pathname === '/login') router.replace('/today');
  }, [state.kind, pathname, router]);

  const logout = useCallback(async () => {
    await logoutRequest();
    // A full reload, on purpose: it drops every in-memory poll and cached page
    // state that belonged to the signed-out user.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- full reload is the point
    window.location.href = '/login';
  }, []);

  return <AuthContext.Provider value={{ state, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth needs an AuthProvider above it');
  return value;
}
