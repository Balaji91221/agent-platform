import type { Stats } from '@/lib/api/schemas';

const CHART_W = 720;
const LEFT = 42;
const RIGHT = 700;

/** Runs per hour, drawn from the real 24 buckets the backend returns. */
export function RunsPerHourChart({ buckets }: { buckets: Stats['runs_per_hour'] }) {
  const peak = Math.max(1, ...buckets.map((b) => b.runs));
  const slot = (RIGHT - LEFT) / Math.max(1, buckets.length);
  const barW = Math.max(6, slot * 0.58);
  const scale = (runs: number) => (runs / peak) * 88;

  const gridValues = [0, Math.round(peak / 2), peak];

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${CHART_W} 138`} className="barchart">
        <defs>
          <linearGradient id="bg2" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2d4470" />
            <stop offset="100%" stopColor="#6b7ea6" />
          </linearGradient>
        </defs>

        <g stroke="#e3e6ec" strokeWidth="1">
          {gridValues.map((v) => (
            <line key={v} x1={LEFT} y1={112 - (v / peak) * 88} x2={RIGHT} y2={112 - (v / peak) * 88} />
          ))}
        </g>
        <g fontSize="10" fill="#6b7280" fontFamily="Roboto,sans-serif">
          {gridValues.map((v) => (
            <text key={v} x="32" y={116 - (v / peak) * 88} textAnchor="end">
              {v}
            </text>
          ))}
          {buckets.map((b, i) =>
            i % 6 === 0 ? (
              <text key={`h${i}`} x={LEFT + slot * i + slot / 2} y="132" textAnchor="middle">
                {String(b.hour).padStart(2, '0')}:00
              </text>
            ) : null,
          )}
        </g>
        <g fontSize="10.5" fontWeight="500" fill="#2d4470" fontFamily="Roboto,sans-serif">
          {buckets.map((b, i) =>
            b.runs > 0 ? (
              <text
                key={`v${i}`}
                x={LEFT + slot * i + slot / 2}
                y={112 - scale(b.runs) - 7}
                textAnchor="middle"
              >
                {b.runs}
              </text>
            ) : null,
          )}
        </g>
        {buckets.map((b, i) => (
          <rect
            key={`b${i}`}
            x={LEFT + slot * i + (slot - barW) / 2}
            y={112 - scale(b.runs)}
            width={barW}
            height={Math.max(0, scale(b.runs))}
            rx="5"
            fill="url(#bg2)"
          />
        ))}
      </svg>
    </div>
  );
}

const RING_CIRCUMFERENCE = 2 * Math.PI * 54;

export function OutcomeRing({
  outcomes,
  successRate,
}: {
  outcomes: Stats['outcomes'];
  successRate: number;
}) {
  const total = outcomes.succeeded + outcomes.retried_then_passed + outcomes.failed;
  const filled = (successRate / 100) * RING_CIRCUMFERENCE;

  const key = [
    { colour: '#188038', label: 'Succeeded', value: outcomes.succeeded },
    { colour: '#f9ab00', label: 'Retried then passed', value: outcomes.retried_then_passed },
    { colour: '#d93025', label: 'Failed', value: outcomes.failed },
  ];

  return (
    <div className="ringwrap">
      <svg viewBox="0 0 140 140" className="ring">
        <circle cx="70" cy="70" r="54" fill="none" stroke="#e3e6ec" strokeWidth="14" />
        {total > 0 ? (
          <circle
            cx="70"
            cy="70"
            r="54"
            fill="none"
            stroke="#1a6b3c"
            strokeWidth="14"
            strokeLinecap="round"
            strokeDasharray={`${filled} ${RING_CIRCUMFERENCE}`}
            transform="rotate(-90 70 70)"
          />
        ) : null}
        <text x="70" y="68" textAnchor="middle" fontSize="26" fontWeight="500" fill="#171a1f">
          {total > 0 ? `${successRate}%` : '—'}
        </text>
        <text x="70" y="88" textAnchor="middle" fontSize="11" fill="#5f6368">
          succeeded
        </text>
      </svg>
      <ul className="ringkey">
        {key.map((k) => (
          <li key={k.label}>
            <i style={{ background: k.colour }} />
            {k.label}
            <b>{k.value}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BusiestAgents({ agents }: { agents: Stats['busiest_agents'] }) {
  if (!agents.length) {
    return (
      <p className="hint" style={{ margin: 0 }}>
        No runs yet.
      </p>
    );
  }
  const top = Math.max(...agents.map((a) => a.runs));
  return (
    <ul className="talist">
      {agents.map((a) => (
        <li key={a.name}>
          <span className="ta-n">{a.name}</span>
          <span className="ta-bar">
            <i style={{ width: `${(a.runs / top) * 100}%`, background: '#2d4470' }} />
          </span>
          <span className="ta-v">{a.runs}</span>
        </li>
      ))}
    </ul>
  );
}
