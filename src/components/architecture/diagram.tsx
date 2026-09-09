type Box = {
  x: number;
  y: number;
  title: string;
  sub: string;
  fill: string;
  stroke: string;
};

type Edge = {
  d: string;
  label?: { x: number; y: number; w: number; text: string };
  dashed?: boolean;
};

const BOXES: Box[] = [
  { x: 340, y: 16, title: 'Browser', sub: 'Forms, chat, and the team thread', fill: '#f4f5f7', stroke: '#6b7280' },
  { x: 340, y: 106, title: 'Web API', sub: 'Creates agents, takes messages', fill: '#eef1f7', stroke: '#2d4470' },
  { x: 640, y: 106, title: 'PostgreSQL', sub: 'Agents, runs, teams, credentials', fill: '#e9f3ed', stroke: '#1a6b3c' },
  { x: 40, y: 196, title: 'Lead agent', sub: 'Routes team work by job title', fill: '#eef1f7', stroke: '#2d4470' },
  { x: 340, y: 196, title: 'Scheduler', sub: 'Wakes every 30s, finds what is due', fill: '#eef1f7', stroke: '#2d4470' },
  { x: 340, y: 286, title: 'Job queue', sub: 'Holds work, one job per run', fill: '#fbf1db', stroke: '#8a5a00' },
  { x: 40, y: 376, title: 'Model API', sub: 'Decides the next step', fill: '#f1eef6', stroke: '#5b4a7d' },
  { x: 340, y: 376, title: 'Worker', sub: 'Runs the agent loop', fill: '#eef1f7', stroke: '#2d4470' },
  { x: 640, y: 376, title: 'Notifier', sub: 'Email, Slack DM, or webhook', fill: '#f1eef6', stroke: '#5b4a7d' },
  { x: 340, y: 466, title: 'Tool router', sub: 'Built-in tool, or an MCP tool', fill: '#eef1f7', stroke: '#2d4470' },
  { x: 40, y: 556, title: 'MCP client', sub: 'Calls discovered tools', fill: '#f1eef6', stroke: '#5b4a7d' },
  { x: 340, y: 556, title: 'Connector layer', sub: 'Per-app adapters', fill: '#f1eef6', stroke: '#5b4a7d' },
  {
    x: 640,
    y: 556,
    title: 'Credential store',
    sub: 'Tokens and keys, decrypt on use',
    fill: '#e9f3ed',
    stroke: '#1a6b3c',
  },
  { x: 40, y: 646, title: 'MCP servers', sub: 'Linear, internal docs', fill: '#f4f5f7', stroke: '#6b7280' },
  { x: 340, y: 646, title: 'Slack, Gmail, Zendesk', sub: 'The real accounts', fill: '#f4f5f7', stroke: '#6b7280' },
];

const EDGES: Edge[] = [
  { d: 'M440,72 L440,106' },
  { d: 'M440,162 L440,196', label: { x: 389.6, y: 170, w: 100.8, text: 'saves schedule' } },
  { d: 'M440,252 L440,286', label: { x: 411.3, y: 260, w: 57.4, text: 'due now' } },
  { d: 'M440,342 L440,376', label: { x: 408.2, y: 350, w: 63.6, text: 'picks up' } },
  { d: 'M440,432 L440,466', label: { x: 405.1, y: 440, w: 69.8, text: 'tool call' } },
  { d: 'M440,522 L440,556', label: { x: 408.2, y: 530, w: 63.6, text: 'built-in' } },
  { d: 'M440,612 L440,646', label: { x: 417.5, y: 620, w: 45, text: 'HTTPS' } },
  { d: 'M140,612 L140,646', label: { x: 117.5, y: 620, w: 45, text: 'HTTPS' } },
  { d: 'M340,494 L240,556', label: { x: 273.7, y: 516, w: 32.6, text: 'MCP' } },
  { d: 'M540,134 L640,134', label: { x: 539.6, y: 125, w: 100.8, text: 'reads / writes' } },
  { d: 'M540,224 L640,180', dashed: true },
  { d: 'M540,378 L640,180', dashed: true, label: { x: 561.3, y: 270, w: 57.4, text: 'run log' } },
  { d: 'M240,390 L340,390' },
  { d: 'M340,404 L240,404', label: { x: 264.4, y: 395, w: 51.2, text: 'prompt' } },
  { d: 'M540,404 L640,404', label: { x: 561.3, y: 395, w: 57.4, text: 'outcome' } },
  { d: 'M540,584 L640,584', label: { x: 548.9, y: 575, w: 82.2, text: 'needs token' } },
  { d: 'M340,148 L240,206', label: { x: 245.8, y: 168, w: 88.4, text: 'team message' } },
  { d: 'M240,240 L340,300', label: { x: 255.1, y: 261, w: 69.8, text: 'delegates' } },
];

const LEGEND = [
  { background: '#eef1f7', borderColor: '#2d4470', label: 'Application code' },
  { background: '#fbf1db', borderColor: '#a56b00', label: 'Queue' },
  { background: '#e9f3ed', borderColor: '#188038', label: 'Storage' },
  { background: '#f1eef6', borderColor: '#8430ce', label: 'Outbound calls' },
  { background: '#f4f5f7', borderColor: '#5f6368', label: 'Outside the system' },
];

export function SystemDiagram() {
  return (
    <>
      <div className="diagram">
        <svg
          style={{ maxWidth: 860, margin: '0 auto' }}
          viewBox="0 0 880 730"
          role="img"
          aria-label="System architecture diagram"
        >
          <defs>
            <marker id="ar" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">
              <path d="M0,1 L8,4.5 L0,8 z" fill="#a8adb8" />
            </marker>
          </defs>

          {EDGES.map((e) => (
            <g key={e.d}>
              <path
                d={e.d}
                fill="none"
                stroke="#a8adb8"
                strokeWidth="1.6"
                strokeDasharray={e.dashed ? '5 4' : undefined}
                markerEnd="url(#ar)"
              />
              {e.label ? (
                <>
                  <rect x={e.label.x} y={e.label.y} width={e.label.w} height="18" rx="9" fill="#fff" />
                  <text
                    x={e.label.x + e.label.w / 2}
                    y={e.label.y + 13}
                    textAnchor="middle"
                    fontSize="10.5"
                    fill="#6b7280"
                  >
                    {e.label.text}
                  </text>
                </>
              ) : null}
            </g>
          ))}

          {BOXES.map((b) => (
            <g key={b.title}>
              <rect
                x={b.x}
                y={b.y}
                width="200"
                height="56"
                rx="14"
                fill={b.fill}
                stroke={b.stroke}
                strokeWidth="1.5"
              />
              <text x={b.x + 100} y={b.y + 24} textAnchor="middle" fontSize="13" fontWeight="500" fill={b.stroke}>
                {b.title}
              </text>
              <text x={b.x + 100} y={b.y + 41} textAnchor="middle" fontSize="10.5" fill="#6b7280">
                {b.sub}
              </text>
            </g>
          ))}
        </svg>
      </div>

      <div className="dlegend">
        {LEGEND.map((l) => (
          <span key={l.label}>
            <i style={{ background: l.background, borderColor: l.borderColor }} />
            {l.label}
          </span>
        ))}
      </div>
    </>
  );
}
