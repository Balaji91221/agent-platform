'use client';

import { Suspense, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import { ConnectCard } from '@/components/connections/connect-card';
import type { Provider } from '@/components/connections/connect-card';
import { McpServers } from '@/components/connections/mcp-servers';
import {
  GlobeIcon,
  LinearIcon,
  MailIcon,
  NotionIcon,
  SheetsIcon,
  SlackIcon,
  StripeIcon,
  ZendeskIcon,
  PlayIcon,
} from '@/components/icons';
import { Loaded, Problem } from '@/components/states';
import { PageHead } from '@/components/ui';
import { listConnections, listTools } from '@/lib/api/endpoints';
import { useLoad } from '@/lib/api/use-load';

const PROVIDERS: Provider[] = [
  { name: 'Gmail', provider: 'gmail', sub: 'Google account', blurb: 'Read unread mail, open a message, send as you.', background: 'linear-gradient(140deg,#ea4335,#c5221f)', icon: <MailIcon />, auth: 'oauth' },
  { name: 'Slack', provider: 'slack', sub: 'Workspace', blurb: 'Post to a channel, read history, look up members.', background: 'linear-gradient(140deg,#611f69,#8e4a94)', icon: <SlackIcon />, auth: 'oauth' },
  { name: 'Google Sheets', provider: 'sheets', sub: 'Google account', blurb: 'Read rows, append rows, update a range.', background: 'linear-gradient(140deg,#34a853,#1e8e3e)', icon: <SheetsIcon />, auth: 'oauth' },
  { name: 'Zendesk', provider: 'zendesk', sub: 'Subdomain', blurb: 'List new tickets, add labels, escalate.', background: 'linear-gradient(140deg,#03363d,#1a5f68)', icon: <ZendeskIcon />, auth: 'oauth' },
  { name: 'Notion', provider: 'notion', sub: 'OAuth', blurb: 'Read a page or database, create a page.', background: 'linear-gradient(140deg,#3c4043,#5f6368)', icon: <NotionIcon />, auth: 'oauth' },
  { name: 'Linear', provider: 'linear', sub: 'OAuth', blurb: 'Create issues, move them between states.', background: 'linear-gradient(140deg,#5e6ad2,#7c8ae0)', icon: <LinearIcon />, auth: 'oauth' },
  { name: 'Stripe', provider: 'stripe', sub: 'API key', blurb: 'Read charges, invoices, and customers.', background: 'linear-gradient(140deg,#3b6fd6,#2a55b3)', icon: <StripeIcon />, auth: 'api_key' },
  { name: 'YouTube', provider: 'youtube', sub: 'API key', blurb: 'Video metadata, view counts, and search.', background: 'linear-gradient(140deg,#c4302b,#ff5a4f)', icon: <PlayIcon />, auth: 'api_key' },
  { name: 'Custom HTTP', provider: 'http', sub: 'Your own endpoint', blurb: 'Point at any REST endpoint with your own auth header.', background: 'linear-gradient(140deg,#5f6368,#80868b)', icon: <GlobeIcon />, auth: 'custom_http' },
];

/** What the OAuth callback said when it bounced the browser back here. */
function OAuthBanner() {
  const params = useSearchParams();
  const connected = params.get('connected');
  const error = params.get('oauth_error');
  if (connected) {
    return <p className="hint" style={{ color: 'var(--ok)' }}>{connected} connected.</p>;
  }
  if (error) {
    return <Problem message={`Sign-in failed: ${error}`} />;
  }
  return null;
}

export default function ConnectionsPage() {
  const connections = useLoad(useCallback((signal) => listConnections(signal), []));
  const tools = useLoad(useCallback((signal) => listTools(signal), []));
  const available = new Set(tools.state.kind === 'ready' ? tools.state.data.map((t) => t.provider) : []);

  return (
    <>
      <PageHead
        title="Connections"
        blurb="Apps your agents can reach. Each one is authorised once, stored encrypted, and refreshed automatically before every run."
      />

      <Suspense fallback={null}>
        <OAuthBanner />
      </Suspense>

      <Loaded state={connections.state}>
        {(rows) => (
          <div className="cgrid">
            {PROVIDERS.map((card) => (
              <ConnectCard
                key={card.provider}
                card={card}
                live={rows.find((c) => c.provider === card.provider)}
                available={tools.state.kind !== 'ready' || available.has(card.provider)}
                onChanged={connections.reload}
              />
            ))}
          </div>
        )}
      </Loaded>

      <McpServers />
    </>
  );
}
