'use client';

import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { screenFor } from '@/lib/screen';

/* The stylesheet scopes some rules by screen id (#chat, #agents, #mate), so the
   route's name has to survive onto the section element. */
export function Screen({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const id = screenFor(pathname);

  return (
    <section className="screen on" id={id}>
      {children}
    </section>
  );
}
