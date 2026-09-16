'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { listNotifications } from '@/lib/api/endpoints';
import { useLoad } from '@/lib/api/use-load';
import { SCREEN_TITLES } from '@/lib/data';
import { titleFor } from '@/lib/screen';
import { BellIcon, PlusIcon, SearchIcon } from './icons';
import { SearchPalette } from './search-palette';

export function Topbar() {
  const pathname = usePathname();
  const params = useSearchParams();
  const editing = pathname === '/create' && params.get('edit') !== null;
  const title = editing ? 'Edit agent' : titleFor(pathname, SCREEN_TITLES);
  const feed = useLoad(useCallback((signal) => listNotifications(signal), []), { pollMs: 15000 });
  const unread = feed.state.kind === 'ready' ? feed.state.data.filter((n) => !n.is_read).length : 0;
  const [searching, setSearching] = useState(false);
  // These pages carry their own New agent button; two of them a centimetre apart reads as a bug.
  const ownsNewAgent = pathname === '/create' || pathname === '/agents';

  // ⌘K / Ctrl+K opens the palette from anywhere in the workspace.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearching(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <header className="topbar">
      <div className="crumb">
        <span>Relay</span>
        <span>/</span>
        <b>{title}</b>
      </div>
      <div className="tb-right">
        <button className="search-pill" aria-label="Search agents" onClick={() => setSearching(true)}>
          <SearchIcon size={15} />
          <span>Search agents</span>
          <kbd>⌘K</kbd>
        </button>
        <SearchPalette open={searching} onClose={() => setSearching(false)} />
        <Link
          className="icon-btn"
          href="/notifications"
          aria-label={unread ? `${unread} unread notifications` : 'Notifications'}
          style={{ position: 'relative' }}
        >
          <BellIcon />
          {unread ? <span className="notif-dot">{unread > 99 ? '99+' : unread}</span> : null}
        </Link>
        {ownsNewAgent ? null : (
          <Link className="btn" href="/create">
            <PlusIcon />
            New agent
          </Link>
        )}
      </div>
    </header>
  );
}
