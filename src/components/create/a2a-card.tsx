import { CardHead, Switch } from '../ui';

type Props = {
  enabled: boolean;
  onToggle: () => void;
};

/**
 * The per-agent half of A2A (Agent2Agent). The server half is `A2A_ENABLED` in
 * the backend; the Deployment card on the agent page says which of the two is off.
 */
export function A2ACard({ enabled, onToggle }: Props) {
  return (
    <div className="card">
      <CardHead
        title="Agent-to-agent (A2A)"
        blurb="Let other agents discover this one and send it work."
        aside={<Switch pressed={enabled} label="Reachable over A2A" onToggle={onToggle} />}
      />
      <div className="card-body" style={{ fontSize: '12.5px', color: 'var(--ink-2)' }}>
        {enabled ? (
          <>
            An agent card is published at{' '}
            <span className="mono">/a2a/agents/&#123;id&#125;/.well-known/agent-card.json</span> and a
            JSON-RPC <span className="mono">SendMessage</span> endpoint runs this agent for any caller
            holding its bearer token. The card lists the tools it holds, and its user prompt as an
            example, so keep secrets out of the prompt. The token is on the agent page.
          </>
        ) : (
          <>
            Off. Nothing about this agent is published, and the A2A routes answer 404 for it. Turn it
            on to let another agent, on this platform or elsewhere, hand it work.
          </>
        )}
      </div>
    </div>
  );
}
