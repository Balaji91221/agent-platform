import type { ReactNode } from 'react';
import { AlertCircleIcon, CheckCircleIcon, CheckIcon, ClockCircleIcon } from '../icons';
import type { Stats } from '@/lib/api/schemas';

type Tile = {
  label: string;
  value: string;
  unit: string;
  icon: ReactNode;
  iconStyle: { background: string; color: string };
};

/* The backend returns no trend history, so the tiles show the figure only —
   a real number beside an invented "+2 vs yesterday" would be worse than none. */
export function Tiles({ stats }: { stats: Stats }) {
  const tiles: Tile[] = [
    {
      label: 'Runs today',
      value: String(stats.runs_today),
      unit: `of ${stats.runs_total}`,
      icon: <CheckIcon strokeWidth={2.6} />,
      iconStyle: { background: '#2d44701f', color: '#1a73e8' },
    },
    {
      label: 'Success rate',
      value: String(stats.success_rate),
      unit: '%',
      icon: <CheckCircleIcon />,
      iconStyle: { background: '#1a6b3c14', color: '#1a6b3c' },
    },
    {
      label: 'Median duration',
      value:
        stats.median_duration_seconds === null
          ? '—'
          : String(Math.round(stats.median_duration_seconds * 10) / 10),
      unit: stats.median_duration_seconds === null ? '' : 's',
      icon: <ClockCircleIcon />,
      iconStyle: { background: '#8a5a0014', color: '#8a5a00' },
    },
    {
      label: 'Failures',
      value: String(stats.failures_this_week),
      unit: 'this week',
      icon: <AlertCircleIcon />,
      iconStyle: { background: '#a3231c14', color: '#a3231c' },
    },
  ];

  return (
    <div className="tiles">
      {tiles.map((t) => (
        <div className="tile" key={t.label}>
          <div className="t-top">
            <span className="t-ico" style={t.iconStyle}>
              {t.icon}
            </span>
            <span className="t-lab">{t.label}</span>
          </div>
          <div className="t-val">
            {t.value}
            {t.unit ? <em>{t.unit}</em> : null}
          </div>
        </div>
      ))}
    </div>
  );
}
