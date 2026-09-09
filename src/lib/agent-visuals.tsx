/** Icon and colour for an agent row, chosen from its name — presentation only. */
import type { ReactNode } from 'react';
import {
  AgentIcon,
  InvoiceIcon,
  MailIcon,
  MetricsIcon,
  StandupIcon,
  TriageIcon,
} from '@/components/icons';

const LOOKS: { match: RegExp; background: string; icon: ReactNode }[] = [
  {
    match: /inbox|mail|email|digest/i,
    background: 'linear-gradient(140deg,#3b6fd6,#2a55b3)',
    icon: <MailIcon size={16} strokeWidth={1.9} />,
  },
  {
    match: /standup|reminder|thread/i,
    background: 'linear-gradient(140deg,#9b72cb,#d96570)',
    icon: <StandupIcon />,
  },
  {
    match: /triage|support|ticket/i,
    background: 'var(--run)',
    icon: <TriageIcon />,
  },
  {
    match: /invoice|billing|finance/i,
    background: 'linear-gradient(140deg,#34a853,#1e8e3e)',
    icon: <InvoiceIcon />,
  },
  {
    match: /metric|report|roundup|weekly/i,
    background: 'linear-gradient(140deg,#9aa0a6,#bdc1c6)',
    icon: <MetricsIcon />,
  },
];

export function lookFor(name: string): { background: string; icon: ReactNode } {
  const hit = LOOKS.find((l) => l.match.test(name));
  return hit ?? { background: 'linear-gradient(140deg,#5f6368,#80868b)', icon: <AgentIcon size={16} /> };
}

const APP_COLOURS: Record<string, string> = {
  gmail: '#d93025',
  slack: '#4a154b',
  sheets: '#0f9d58',
  zendesk: '#03363d',
  stripe: '#5e6ad2',
  http: '#5f6368',
};

/** The app chips on an agent row, derived from the tools it may call. */
export function appsFor(toolNames: string[]): { name: string; colour: string }[] {
  const providers = new Set<string>();
  for (const tool of toolNames) {
    if (tool.startsWith('mcp:')) {
      providers.add('mcp');
      continue;
    }
    providers.add(tool.split('.')[0]);
  }
  return [...providers].map((p) => ({
    name: p === 'http' ? 'Custom HTTP' : p.charAt(0).toUpperCase() + p.slice(1),
    colour: APP_COLOURS[p] ?? '#5f6368',
  }));
}
