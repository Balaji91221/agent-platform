'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  addTeammate,
  clearThread,
  getTeam,
  getThread,
  postTeamMessage,
  removeTeammate,
  setLead as setLeadCall,
  updateTeammate,
} from '@/lib/api/endpoints';
import type { TeammatePatch } from '@/lib/api/endpoints';
import type { Team, TeamMessage, Teammate } from '@/lib/api/schemas';
import { useLoad } from '@/lib/api/use-load';
import type { Load } from '@/lib/api/use-load';

type Draft = {
  agentId: number | null;
  name: string;
  title: string;
  description: string;
  lead: boolean;
};

type NewMate = {
  agentId: number;
  name: string;
  title: string;
  description: string;
  lead: boolean;
};

type TeamStore = {
  team: Load<Team>;
  thread: Load<TeamMessage[]>;
  draft: Draft;
  problem: string | null;
  setDraft: (patch: Partial<Draft>) => void;
  makeLead: (id: number) => Promise<void>;
  standDown: () => Promise<void>;
  remove: (id: number) => Promise<void>;
  edit: (id: number, patch: TeammatePatch) => Promise<boolean>;
  addMate: (mate: NewMate) => Promise<boolean>;
  /** False when the message did not reach the server. */
  send: (text: string) => Promise<boolean>;
  reset: () => Promise<void>;
  reload: () => void;
};

const Ctx = createContext<TeamStore | null>(null);

export function useTeam(): TeamStore {
  const store = useContext(Ctx);
  if (!store) throw new Error('useTeam must be used inside <TeamProvider>');
  return store;
}

const EMPTY_DRAFT: Draft = { agentId: null, name: '', title: '', description: '', lead: false };

const someoneRunning = (team: Team): boolean => team.teammates.some((m) => m.is_running);

/** One colour per teammate, in join order, so avatars tell people apart. */
const PALETTE = ['#2d4470', '#1a6b3c', '#8a5a00', '#611f69', '#0b6e7f', '#a3231c', '#3b6fd6', '#5e6ad2'];

/** The roster's state, derived from the agent rather than tracked separately. */
export function stateOf(mate: Teammate, thread: TeamMessage[]): 'idle' | 'working' | 'blocked' {
  if (mate.is_running) return 'working';
  const last = [...thread].reverse().find((m) => m.from_teammate_id === mate.id);
  if (last?.kind === 'blocked') return 'blocked';
  return 'idle';
}

export function TeamProvider({ children }: { children: ReactNode }) {
  const [draft, setDraftState] = useState<Draft>({ ...EMPTY_DRAFT });
  const [problem, setProblem] = useState<string | null>(null);

  // Poll only while somebody is working; an idle room makes no requests.
  // The roster is polled too, or "Working…" never clears and the thread poll
  // never stops (it is the roster that says when a run has ended).
  const teamLoad = useLoad(useCallback((signal) => getTeam(signal), []), {
    pollMs: 2000,
    pollWhile: someoneRunning,
  });
  const anyRunning = teamLoad.state.kind === 'ready' && someoneRunning(teamLoad.state.data);

  const threadLoad = useLoad(useCallback((signal) => getThread(signal), []), {
    pollMs: anyRunning ? 2000 : undefined,
  });

  // One more read shortly after the last run ends, so the reply that landed in
  // the same instant as the lock release is not missed.
  const reloadThread = threadLoad.reload;
  const wasRunning = useRef(false);
  useEffect(() => {
    const was = wasRunning.current;
    wasRunning.current = anyRunning;
    if (!was || anyRunning) return;
    const timer = setTimeout(reloadThread, 1200);
    return () => clearTimeout(timer);
  }, [anyRunning, reloadThread]);

  const reload = useCallback(() => {
    teamLoad.reload();
    threadLoad.reload();
  }, [teamLoad, threadLoad]);

  const setDraft = useCallback((patch: Partial<Draft>) => {
    setDraftState((prev) => ({ ...prev, ...patch }));
  }, []);

  const makeLead = useCallback(
    async (id: number) => {
      const result = await setLeadCall(id);
      if (!result.ok) setProblem(result.error.message);
      teamLoad.reload();
    },
    [teamLoad],
  );

  const standDown = useCallback(async () => {
    const result = await setLeadCall(null);
    if (!result.ok) setProblem(result.error.message);
    teamLoad.reload();
  }, [teamLoad]);

  const remove = useCallback(
    async (id: number) => {
      const result = await removeTeammate(id);
      if (!result.ok) setProblem(result.error.message);
      teamLoad.reload();
    },
    [teamLoad],
  );

  const edit = useCallback(
    async (id: number, patch: TeammatePatch) => {
      setProblem(null);
      const result = await updateTeammate(id, patch);
      if (!result.ok) setProblem(result.error.message);
      teamLoad.reload();
      return result.ok;
    },
    [teamLoad],
  );

  const addMate = useCallback(
    async (mate: NewMate) => {
      setProblem(null);
      const taken = teamLoad.state.kind === 'ready' ? teamLoad.state.data.teammates.length : 0;
      const result = await addTeammate({
        agent_id: mate.agentId,
        display_name: mate.name,
        job_title: mate.title,
        description: mate.description,
        colour: PALETTE[taken % PALETTE.length],
        make_lead: mate.lead,
      });
      if (!result.ok) {
        setProblem(result.error.message);
        return false;
      }
      setDraftState({ ...EMPTY_DRAFT });
      teamLoad.reload();
      return true;
    },
    [teamLoad],
  );

  const send = useCallback(
    async (text: string) => {
      setProblem(null);
      const result = await postTeamMessage(text);
      if (!result.ok) setProblem(result.error.message);
      // The routing decision and the handoff card are already written.
      threadLoad.reload();
      teamLoad.reload();
      return result.ok;
    },
    [threadLoad, teamLoad],
  );

  const reset = useCallback(async () => {
    const result = await clearThread();
    if (!result.ok) setProblem(result.error.message);
    threadLoad.reload();
  }, [threadLoad]);

  const value = useMemo<TeamStore>(
    () => ({
      team: teamLoad.state,
      thread: threadLoad.state,
      draft,
      problem,
      setDraft,
      makeLead,
      standDown,
      remove,
      edit,
      addMate,
      send,
      reset,
      reload,
    }),
    [
      teamLoad.state,
      threadLoad.state,
      draft,
      problem,
      setDraft,
      makeLead,
      standDown,
      remove,
      edit,
      addMate,
      send,
      reset,
      reload,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
