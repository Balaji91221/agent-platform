'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useCallback } from 'react';
import { getStats } from '@/lib/api/endpoints';
import { useLoad } from '@/lib/api/use-load';
import { useAuth } from '@/lib/auth';
import {
  AgentIcon,
  ArchitectureIcon,
  BellIcon,
  ChatIcon,
  ClockMark,
  DashboardIcon,
  LinkIcon,
  TeamIcon,
} from './icons';
import type { ComponentType, SVGProps } from 'react';

type NavItem = {
  href: string;
  label: string;
  Icon: ComponentType<SVGProps<SVGSVGElement> & { size?: number }>;
};

const NAV: NavItem[] = [
  { href: '/today', label: 'Dashboard', Icon: DashboardIcon },
  { href: '/chat', label: 'Build with chat', Icon: ChatIcon },
  { href: '/agents', label: 'Agents', Icon: AgentIcon },
  { href: '/team', label: 'Team', Icon: TeamIcon },
  { href: '/connections', label: 'Connections', Icon: LinkIcon },
  { href: '/notifications', label: 'Notifications', Icon: BellIcon },
  { href: '/architecture', label: 'Architecture', Icon: ArchitectureIcon },
];

export function Sidebar() {
  const pathname = usePathname();
  const plan = useLoad(useCallback((signal) => getStats('today', signal), []), { pollMs: 15000 });
  const auth = useAuth();
  const me = auth.state.kind === 'signed-in' ? auth.state.me : null;
  const displayName = me?.name || me?.email || 'Signed out';
  const initials = displayName
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('');

  return (
    <aside className="side">
      <div className="logo">
        <span className="mark">
          <ClockMark />
        </span>
        <b>Relay</b>
      </div>

      <nav className="nav">
        <span className="lbl">Workspace</span>
        {NAV.map(({ href, label, Icon }) => (
          <Link key={href} href={href} aria-current={pathname === href ? 'page' : undefined}>
            <Icon />
            {label}
          </Link>
        ))}
      </nav>

      <div className="side-foot">
        <div className="upsell" title="The cap is MAX_AGENTS_PER_USER in the backend .env">
          <div className="upsell-row">
            <b>Agents</b>
            <span>
              {plan.state.kind === 'ready'
                ? `${plan.state.data.agents_used} of ${plan.state.data.agent_limit}`
                : '…'}
            </span>
          </div>
          <div className="usage" aria-hidden="true">
            <i
              style={{
                width:
                  plan.state.kind === 'ready' && plan.state.data.agent_limit > 0
                    ? `${Math.min(100, Math.round((100 * plan.state.data.agents_used) / plan.state.data.agent_limit))}%`
                    : '0%',
              }}
            />
          </div>
          <p>Cap set in the backend, no billing in this build.</p>
        </div>
        <div className="who">
          {me?.picture ? (
            // eslint-disable-next-line @next/next/no-img-element -- Google-hosted avatar, no optimisation needed
            <img className="avatar" src={me.picture} alt="" referrerPolicy="no-referrer" />
          ) : (
            <span className="avatar">{initials || '?'}</span>
          )}
          <div className="who-text">
            <b>{displayName}</b>
            <span>{me?.email ?? ''}</span>
          </div>
          <button className="who-out" onClick={() => void auth.logout()} title="Sign out">
            Sign out
          </button>
        </div>
      </div>
    </aside>
  );
}
