import type { ReactNode } from 'react';
import { CardHead } from '../ui';

type Branch = { when: ReactNode; then: ReactNode; shows: string; tone: 'direct' | 'lead' | 'none' };

const BRANCHES: Branch[] = [
  {
    tone: 'direct',
    when: (
      <>
        You wrote <span className="mono">@name</span>
      </>
    ),
    then: 'Straight to that teammate, the lead included. No routing call, no card.',
    shows: 'direct',
  },
  {
    tone: 'none',
    when: 'Nobody is lead',
    then: 'Nothing runs. The thread says the message is unclaimed, rather than guessing an owner.',
    shows: 'no_lead',
  },
  {
    tone: 'lead',
    when: 'The lead sends it on',
    then: 'A handoff card names who passed it, who has it, and why. That teammate starts.',
    shows: 'handoff',
  },
  {
    tone: 'lead',
    when: 'The lead takes it',
    then: 'Its own agent runs, with tools, like any other teammate.',
    shows: 'lead_self',
  },
  {
    tone: 'lead',
    when: 'The lead just answers',
    then: 'Small talk and who-does-what get a reply in the thread and no run at all.',
    shows: 'lead_reply',
  },
];

export function RoutingCard() {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <CardHead
        title="How a message finds an agent"
        blurb="One thread for the whole team. What happens between pressing send and a teammate replying"
      />
      <div className="branches">
        {BRANCHES.map((b) => (
          <div className={`branch ${b.tone}`} key={b.shows}>
            <div className="bw">{b.when}</div>
            <p>{b.then}</p>
            <span className="mono">{b.shows}</span>
          </div>
        ))}
      </div>
      <p className="note" style={{ margin: '0 20px 20px' }}>
        <span>
          Two things keep this honest. The teammate the lead names is checked against the roster before anything runs,
          and if the model is down a keyword match routes the work or, failing that, the lead answers with who does what.
          A message to a teammate that is already mid-run is held and started the moment that run ends.
        </span>
      </p>
    </div>
  );
}
