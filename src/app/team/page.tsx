'use client';

import Link from 'next/link';
import { useRef } from 'react';
import { GroupChat } from '@/components/team/group-chat';
import type { ChatHandle } from '@/components/team/group-chat';
import { Roster } from '@/components/team/roster';
import { PlusIcon } from '@/components/icons';
import { PageHead } from '@/components/ui';

export default function TeamPage() {
  const chat = useRef<ChatHandle | null>(null);

  return (
    <>
      <PageHead
        title="Team"
        blurb="Your agents as teammates. One of them is the lead — message the team and the lead picks it up, then brings in whoever the job actually needs. Everything happens in one thread, so nothing gets copied between windows."
        actions={
          <Link className="btn" href="/mate">
            <PlusIcon />
            Add teammate
          </Link>
        }
      />

      <div className="teamgrid">
        <Roster onMention={(name) => chat.current?.mention(name)} />
        <GroupChat handleRef={chat} />
      </div>
    </>
  );
}
