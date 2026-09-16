import type { ReactNode } from 'react';
import { CardHead } from '../ui';

type Chain = { title: string; trigger: string; steps: ReactNode[] };

/** All four claim the agent first. Three go through the queue; A2A runs in-process. */
const CHAINS: Chain[] = [
  {
    title: 'You press Run now',
    trigger: 'from an agent page',
    steps: [
      'The API flips the agent to running in one atomic write, or answers 409 if it already was.',
      'A run row is written and the job is pushed.',
      'The page opens the log stream and lines appear as they happen.',
    ],
  },
  {
    title: 'The schedule comes due',
    trigger: 'nobody watching',
    steps: [
      'Every 30 seconds the scheduler asks which agents were due before now and are not running.',
      'It claims each one, writes the run, pushes the job, and sets the next due time.',
      'If the run fails three times, the notifier tells you the way you chose.',
    ],
  },
  {
    title: 'You message the team',
    trigger: 'from the team room',
    steps: [
      'The lead makes one tool-free call and picks handoff, self, or reply.',
      'A handoff writes the card, then queues that teammate.',
      'Its answer goes back into the same thread, under its own name.',
    ],
  },
  {
    title: 'Another agent calls in',
    trigger: 'over A2A, with the agent’s token',
    steps: [
      'The caller reads the public agent card, then sends a JSON-RPC SendMessage.',
      'The API claims the agent with the same lock, or answers busy (-32004).',
      'The run happens in-process while the caller waits, and comes back as a completed or failed task.',
    ],
  },
];

export function FourWaysIn() {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <CardHead
        title="Four ways a run starts"
        blurb="Different triggers, one lock: the agent is claimed first so nothing can run it twice. A2A skips the queue because the caller is waiting"
      />
      <div className="chains">
        {CHAINS.map((c) => (
          <div className="chain" key={c.title}>
            <b>{c.title}</b>
            <span className="trig">{c.trigger}</span>
            <ol>
              {c.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </div>
  );
}
