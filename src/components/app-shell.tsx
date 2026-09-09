'use client';

import { usePathname } from 'next/navigation';
import { Suspense } from 'react';
import type { ReactNode } from 'react';
import { Screen } from '@/components/screen';
import { Sidebar } from '@/components/sidebar';
import { Topbar } from '@/components/topbar';
import { useAuth } from '@/lib/auth';
import { TeamProvider } from '@/lib/team-store';

/** The signed-in chrome (sidebar, topbar, team polling), or the bare login page. */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { state } = useAuth();

  if (pathname === '/login') {
    return <Screen>{children}</Screen>;
  }
  if (state.kind !== 'signed-in') {
    // Nothing to show yet: avoid a flash of the workspace before the redirect.
    return null;
  }
  return (
    <TeamProvider>
      <div className="app">
        <Sidebar />
        <div>
          <Suspense fallback={null}>
            <Topbar />
          </Suspense>
          <div className="wrap">
            <Screen>{children}</Screen>
          </div>
        </div>
      </div>
    </TeamProvider>
  );
}
