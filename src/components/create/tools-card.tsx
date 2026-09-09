'use client';

import Link from 'next/link';
import { useLimits } from '@/lib/api/use-limits';

import { InfoIcon, MailIcon, MailSendIcon, PlayIcon, SheetsIcon, SlackIcon, GlobeIcon } from '../icons';
import { CardHead, Switch } from '../ui';
import type { ToolCatalogueEntry } from '@/lib/api/schemas';

const LOOKS: Record<string, { background: string; icon: React.ReactNode }> = {
  gmail: { background: 'linear-gradient(140deg,#ea4335,#c5221f)', icon: <MailIcon strokeWidth={1.9} /> },
  slack: { background: 'linear-gradient(140deg,#611f69,#8e4a94)', icon: <SlackIcon strokeWidth={1.9} /> },
  sheets: { background: 'linear-gradient(140deg,#34a853,#1e8e3e)', icon: <SheetsIcon /> },
  youtube: { background: 'linear-gradient(140deg,#c4302b,#ff5a4f)', icon: <PlayIcon /> },
  http: { background: 'linear-gradient(140deg,#5f6368,#80868b)', icon: <GlobeIcon /> },
};

type Props = {
  catalogue: ToolCatalogueEntry[];
  enabled: Record<string, boolean>;
  writable: Record<string, boolean>;
  /** Providers with a live connection; undefined while the list is loading. */
  connected?: Set<string>;
  onToggle: (name: string) => void;
  onToggleWrite: (name: string) => void;
};

const PROVIDER_LABEL: Record<string, string> = {
  gmail: 'Gmail',
  slack: 'Slack',
  sheets: 'Google Sheets',
  youtube: 'YouTube',
  http: 'Custom HTTP',
};

export function ToolsCard({
  catalogue,
  enabled,
  writable,
  connected,
  onToggle,
  onToggleWrite,
}: Props) {
  const limits = useLimits();
  const count = catalogue.filter((t) => enabled[t.name]).length;
  const missing = (tool: ToolCatalogueEntry) =>
    connected !== undefined && !!enabled[tool.name] && !connected.has(tool.provider);

  return (
    <div className="card">
      <CardHead
        title="Tools"
        blurb="Only these can be called during a run. Everything else is refused."
        aside={
          <span className={count ? 'badge ok' : 'badge'}>
            {count ? <i /> : null}
            {count} enabled
          </span>
        }
      />
      <div className="card-body" style={{ paddingTop: 4 }}>
        {catalogue.map((tool) => {
          const look = LOOKS[tool.provider] ?? LOOKS.http;
          const on = !!enabled[tool.name];
          return (
            <div className="trow" key={tool.name}>
              <span className="tleft">
                <span className="sq" style={{ width: 32, height: 32, background: look.background }}>
                  {tool.name.endsWith('.send') ? <MailSendIcon /> : look.icon}
                </span>
                <span>
                  <b>
                    {tool.name}
                    <span className={`tag ${tool.writes ? 'write' : 'read'}`} style={{ marginLeft: 8 }}>
                      {tool.writes ? 'writes' : 'read'}
                    </span>
                  </b>
                  <span>{tool.description}</span>
                  {missing(tool) ? (
                    <span className="tool-warn">
                      {PROVIDER_LABEL[tool.provider] ?? tool.provider} is not connected, so this
                      call will be blocked. <Link href="/connections">Connect it</Link>
                    </span>
                  ) : null}
                </span>
              </span>
              <span style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                {on && tool.writes ? (
                  <button
                    className={writable[tool.name] ? 'badge err' : 'badge'}
                    onClick={() => onToggleWrite(tool.name)}
                    title="Allow this tool to change things in the real app"
                  >
                    {writable[tool.name] ? 'can write' : 'read only'}
                  </button>
                ) : null}
                <Switch pressed={on} label={`Enable ${tool.name}`} onToggle={() => onToggle(tool.name)} />
              </span>
            </div>
          );
        })}
        <p className="note">
          <InfoIcon />
          <span>
            A run is capped at {limits.max_tool_calls_per_run} tool calls. A tool marked{' '}
            <b style={{ fontWeight: 800, color: 'var(--run)' }}>writes</b> only acts for real once you
            switch it to <b style={{ fontWeight: 800 }}>can write</b>.
          </span>
        </p>
      </div>
    </div>
  );
}
