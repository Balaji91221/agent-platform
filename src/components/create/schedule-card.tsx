'use client';

import { CardHead, Switch } from '../ui';
import { FREQUENCIES, cronFor, nextRuns } from '@/lib/schedule';

type Props = {
  freq: number;
  at: string;
  tz: string;
  enabled: boolean;
  customCron: string;
  onCustomCron: (value: string) => void;
  onFreq: (index: number) => void;
  onAt: (value: string) => void;
  onTz: (value: string) => void;
  onToggle: () => void;
};

const ZONES = ['Asia/Kolkata', 'UTC', 'America/New_York'];

export function ScheduleCard({
  freq, at, tz, enabled, customCron, onCustomCron, onFreq, onAt, onTz, onToggle,
}: Props) {
  const current = FREQUENCIES[freq];
  const cron = customCron.trim() || cronFor(freq, at);
  const runs = customCron.trim() ? [] : nextRuns(current.cron, at);

  return (
    <div className="card">
      <CardHead
        title="Schedule"
        blurb="When this agent runs on its own."
        aside={
          <Switch pressed={enabled} label="Run on a schedule" onToggle={onToggle} />
        }
      />
      <div className="card-body" style={enabled ? undefined : { opacity: 0.45, pointerEvents: 'none' }}>
        <div className="fld">
          <label>How often</label>
          <div className="seg">
            {FREQUENCIES.map((f, i) => (
              <button
                key={f.cron}
                aria-pressed={!customCron.trim() && freq === i}
                onClick={() => onFreq(i)}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
        <div className="fld">
          <label htmlFor="cron">Or a cron rule of your own</label>
          <input
            className="inp mono"
            id="cron"
            placeholder="0 */2 * * *"
            value={customCron}
            onChange={(e) => onCustomCron(e.target.value)}
          />
        </div>
        <div className="row2">
          <div className="fld">
            <label htmlFor="tm">At</label>
            <input className="inp" id="tm" type="time" value={at} onChange={(e) => onAt(e.target.value)} />
          </div>
          <div className="fld">
            <label htmlFor="tz">Timezone</label>
            <select className="inp" id="tz" value={tz} onChange={(e) => onTz(e.target.value)}>
              {ZONES.map((z) => (
                <option key={z}>{z}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="cronbox">
          <span style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--ink-2)' }}>
            {customCron.trim() ? 'Custom rule' : current.words}
          </span>
          <span className="mono">{cron}</span>
        </div>
        <div className="divider" />
        <div className="fld" style={{ marginBottom: 0 }}>
          <label>Next three runs</label>
          <ul className="nextruns">
            {customCron.trim() ? (
              <li>
                <i />
                Shown on the agent page once saved
              </li>
            ) : null}
            {runs.map((r) => (
              <li key={r}>
                <i />
                {r}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
