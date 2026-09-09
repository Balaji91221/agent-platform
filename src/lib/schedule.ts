export type Frequency = {
  label: string;
  cron: string;
  words: string;
};

export const FREQUENCIES: Frequency[] = [
  { label: 'Every 15 min', cron: '*/15 * * * *', words: 'Every 15 minutes' },
  { label: 'Hourly', cron: '0 * * * *', words: 'Every hour, on the hour' },
  { label: 'Daily', cron: '0 9 * * *', words: 'Every day at 09:00' },
  { label: 'Weekdays', cron: '0 9 * * 1-5', words: 'Weekdays at 09:00' },
  { label: 'Weekly', cron: '0 17 * * 5', words: 'Fridays at 17:00' },
];

/* The next three firing times for a cron, given the "At" time the user picked.
   Fixed-clock crons ignore the time field, exactly as the original did. */
export function nextRuns(cron: string, at: string): string[] {
  const t = at || '09:00';
  switch (cron) {
    case '*/15 * * * *':
      return ['Today, 14:30', 'Today, 14:45', 'Today, 15:00'];
    case '0 * * * *':
      return ['Today, 15:00', 'Today, 16:00', 'Today, 17:00'];
    case '0 9 * * *':
    case '0 9 * * 1-5':
      return [`Tomorrow, ${t}`, `Thu 10 Sep, ${t}`, `Fri 11 Sep, ${t}`];
    case '0 17 * * 5':
      return ['Fri 11 Sep, 17:00', 'Fri 18 Sep, 17:00', 'Fri 25 Sep, 17:00'];
    default:
      return [];
  }
}

/** Presets that carry a clock time; the rest are fixed. */
const TIMED: Record<number, (h: string, m: string) => string> = {
  2: (h, m) => `${m} ${h} * * *`,
  3: (h, m) => `${m} ${h} * * 1-5`,
  4: (h, m) => `${m} ${h} * * 5`,
};

/** The cron to save for a preset plus the "At" time the user picked. */
export function cronFor(freq: number, at: string): string {
  const [h = '9', m = '0'] = (at || '09:00').split(':');
  const build = TIMED[freq];
  return build ? build(String(Number(h)), String(Number(m))) : FREQUENCIES[freq].cron;
}

/** The preset + time a saved cron came from, or null when it is a custom rule. */
export function presetFor(cron: string): { freq: number; at: string } | null {
  const fixed = FREQUENCIES.findIndex((f) => f.cron === cron);
  if (fixed === 0 || fixed === 1) return { freq: fixed, at: '09:00' };
  const m = /^(\d{1,2}) (\d{1,2}) \* \* (\*|1-5|5)$/.exec(cron.trim());
  if (!m) return null;
  const at = `${m[2].padStart(2, '0')}:${m[1].padStart(2, '0')}`;
  const freq = m[3] === '*' ? 2 : m[3] === '1-5' ? 3 : 4;
  return { freq, at };
}
