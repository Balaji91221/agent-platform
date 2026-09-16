/**
 * The system in four bands: you, the control plane, the execution plane, and
 * everything outside Relay. Paths are orthogonal on purpose — a diagonal in a
 * lane diagram reads as "special", and none of these edges are.
 */

type Tone = 'app' | 'queue' | 'store' | 'out' | 'ext';

const TONE: Record<Tone, { fill: string; stroke: string; label: string }> = {
  app: { fill: '#eef2f8', stroke: '#2f4a7a', label: 'Relay code' },
  queue: { fill: '#fdf3de', stroke: '#8a5a00', label: 'Queue' },
  store: { fill: '#e8f4ec', stroke: '#1a6b3c', label: 'Storage' },
  out: { fill: '#f2eef8', stroke: '#5b4a7d', label: 'Leaves Relay' },
  ext: { fill: '#f3f4f6', stroke: '#5f6368', label: 'Not ours' },
};

type Lane = { y: number; h: number; name: string };

const LANES: Lane[] = [
  { y: 8, h: 84, name: 'You' },
  { y: 104, h: 244, name: 'Control plane' },
  { y: 360, h: 248, name: 'Execution' },
  { y: 620, h: 84, name: 'Outside Relay' },
];

type Box = { x: number; y: number; title: string; sub: string; tone: Tone };

const W = 200;
const H = 54;

const BOXES: Box[] = [
  { x: 390, y: 24, title: 'Browser', sub: 'Form · chat · team thread', tone: 'ext' },

  { x: 390, y: 120, title: 'Web API', sub: 'FastAPI, every screen calls it', tone: 'app' },
  { x: 680, y: 120, title: 'PostgreSQL', sub: 'Agents · runs · team · tokens', tone: 'store' },
  { x: 100, y: 200, title: 'Team router', sub: 'Lead decides who takes it', tone: 'app' },
  { x: 680, y: 200, title: 'Scheduler', sub: 'Wakes every 30s', tone: 'app' },
  { x: 390, y: 280, title: 'Job queue', sub: 'Redis, one job per run', tone: 'queue' },

  { x: 100, y: 376, title: 'Model API', sub: 'NVIDIA · Anthropic', tone: 'out' },
  { x: 390, y: 376, title: 'Worker', sub: 'Runs the agent loop', tone: 'app' },
  { x: 390, y: 456, title: 'Tool router', sub: 'Picks the caller, loads the token', tone: 'app' },
  { x: 680, y: 456, title: 'Credential store', sub: 'Encrypted, decrypted on use', tone: 'store' },
  { x: 100, y: 536, title: 'MCP client', sub: 'Tools it discovered', tone: 'out' },
  { x: 390, y: 536, title: 'Connectors', sub: 'Gmail · Slack · Sheets · YouTube', tone: 'out' },
  { x: 680, y: 536, title: 'Notifier', sub: 'Reads quiet hours first', tone: 'app' },

  { x: 100, y: 636, title: 'MCP servers', sub: 'Whatever you registered', tone: 'ext' },
  { x: 390, y: 636, title: 'Your accounts', sub: 'The real inbox, the real channel', tone: 'ext' },
  { x: 680, y: 636, title: 'You get told', sub: 'Email · Slack DM · webhook', tone: 'ext' },
];

type Edge = { d: string; text?: string; at?: [number, number]; dashed?: boolean };

const EDGES: Edge[] = [
  { d: 'M490,78 V120' },

  { d: 'M590,147 H680', text: 'reads / writes', at: [592, 129] },
  { d: 'M780,174 V200', text: 'what is due', at: [786, 178], dashed: true },

  { d: 'M490,174 V280', text: 'Run now', at: [497, 210] },
  { d: 'M490,187 H200 V200', text: 'team message', at: [246, 168] },

  { d: 'M200,254 V307 H390', text: 'delegates', at: [252, 288] },
  { d: 'M780,254 V307 H590', text: 'due now', at: [640, 288] },

  { d: 'M490,334 V376', text: 'picks up', at: [497, 344] },

  { d: 'M390,390 H300', text: 'prompt', at: [316, 381] },
  { d: 'M300,416 H390', text: 'answer', at: [316, 407] },

  { d: 'M490,430 V456', text: 'tool call', at: [497, 432] },
  { d: 'M590,483 H680', text: 'decrypt', at: [598, 465] },
  { d: 'M490,510 V536', text: 'built-in name', at: [497, 512] },
  { d: 'M390,483 H200 V536', text: 'mcp: name', at: [212, 494] },

  { d: 'M400,376 V366 H40 V51 H390', text: 'live log, under 2s', at: [55, 150], dashed: true },
  { d: 'M600,376 V352 H930 V147 H880', text: 'run log', at: [896, 250], dashed: true },
  { d: 'M590,403 H920 V563 H880', text: 'outcome', at: [700, 385] },

  { d: 'M200,590 V636', text: 'HTTPS', at: [207, 598] },
  { d: 'M490,590 V636', text: 'HTTPS', at: [497, 598] },
  { d: 'M780,590 V636', text: 'if it matters', at: [787, 598] },
];

/** Pills are sized from the text so a wording change cannot clip a label. */
const pill = (text: string) => Math.round(text.length * 5.4 + 14);

const LEGEND: Tone[] = ['app', 'queue', 'store', 'out', 'ext'];

export function SystemDiagram() {
  return (
    <>
      <div className="diagram">
        <svg viewBox="0 0 980 720" role="img" aria-label="Relay system architecture, four bands">
          <defs>
            <marker id="ar" markerWidth="9" markerHeight="9" refX="7.5" refY="4.5" orient="auto">
              <path d="M0,1 L8,4.5 L0,8 z" fill="#9aa0a6" />
            </marker>
          </defs>

          {LANES.map((lane) => (
            <g key={lane.name}>
              <rect
                x="8"
                y={lane.y}
                width="964"
                height={lane.h}
                rx="16"
                fill="#fafbfc"
                stroke="#edeff2"
                strokeWidth="1"
              />
              <text x="24" y={lane.y + 20} fontSize="9.5" letterSpacing="0.09em" fill="#9aa0a6">
                {lane.name.toUpperCase()}
              </text>
            </g>
          ))}

          {EDGES.map((e) => (
            <g key={e.d}>
              <path
                d={e.d}
                fill="none"
                stroke="#9aa0a6"
                strokeWidth="1.5"
                strokeLinejoin="round"
                strokeDasharray={e.dashed ? '5 4' : undefined}
                markerEnd="url(#ar)"
              />
              {e.text && e.at ? (
                <>
                  <rect x={e.at[0]} y={e.at[1]} width={pill(e.text)} height="17" rx="8.5" fill="#fff" />
                  <text
                    x={e.at[0] + pill(e.text) / 2}
                    y={e.at[1] + 12}
                    textAnchor="middle"
                    fontSize="10"
                    fill="#6b7280"
                  >
                    {e.text}
                  </text>
                </>
              ) : null}
            </g>
          ))}

          {BOXES.map((b) => {
            const tone = TONE[b.tone];
            return (
              <g key={b.title}>
                <rect
                  x={b.x}
                  y={b.y}
                  width={W}
                  height={H}
                  rx="12"
                  fill={tone.fill}
                  stroke={tone.stroke}
                  strokeWidth="1.4"
                />
                <text
                  x={b.x + W / 2}
                  y={b.y + 23}
                  textAnchor="middle"
                  fontSize="13"
                  fontWeight="500"
                  fill={tone.stroke}
                >
                  {b.title}
                </text>
                <text x={b.x + W / 2} y={b.y + 40} textAnchor="middle" fontSize="10.5" fill="#6b7280">
                  {b.sub}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="dlegend">
        {LEGEND.map((t) => (
          <span key={t}>
            <i style={{ background: TONE[t].fill, borderColor: TONE[t].stroke }} />
            {TONE[t].label}
          </span>
        ))}
        <span>
          <i className="dashed" />
          Data, not work
        </span>
      </div>
    </>
  );
}
