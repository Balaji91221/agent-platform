'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense, useCallback, useState } from 'react';
import { AgentForm, DEFAULT_SEED } from '@/components/create/agent-form';
import type { FormSeed } from '@/components/create/agent-form';
import { Loaded } from '@/components/states';
import { getAgent } from '@/lib/api/endpoints';
import { agentDraftSchema } from '@/lib/api/schemas';
import { useLoad } from '@/lib/api/use-load';

export const DRAFT_KEY = 'relay:draft';

/**
 * A draft handed over from the chat builder, read once on mount.
 *
 * sessionStorage is a boundary like any other, so the value is parsed rather
 * than trusted, and the read is guarded for the server pass.
 */
function takeDraft(): FormSeed | null {
  if (typeof window === 'undefined') return null;
  const raw = window.sessionStorage.getItem(DRAFT_KEY);
  if (!raw) return null;
  window.sessionStorage.removeItem(DRAFT_KEY);
  try {
    const parsed = agentDraftSchema.safeParse(JSON.parse(raw));
    if (!parsed.success) return null;
    const d = parsed.data;
    return {
      name: d.name,
      description: d.description,
      system_prompt: d.system_prompt,
      user_prompt: d.user_prompt,
      model: d.model,
      tools: d.tools.map((t) => ({ tool_name: t, can_write: false })),
      schedule: { cron: d.cron, timezone: d.timezone },
      a2a_enabled: false,
    };
  } catch {
    return null;
  }
}

export default function CreatePage() {
  return (
    <Suspense fallback={null}>
      <CreateOrEdit />
    </Suspense>
  );
}

function CreateOrEdit() {
  const params = useSearchParams();
  const editId = Number(params.get('edit')) || null;
  const [handover] = useState(takeDraft);

  if (editId === null) {
    return <AgentForm seed={handover ?? DEFAULT_SEED} />;
  }
  return <EditExisting id={editId} />;
}

function EditExisting({ id }: { id: number }) {
  const agent = useLoad(useCallback((signal) => getAgent(id, signal), [id]));
  return (
    <Loaded state={agent.state}>
      {(a) => (
        <AgentForm
          key={a.id}
          editingId={a.id}
          seed={{
            name: a.name,
            description: a.description,
            system_prompt: a.system_prompt,
            user_prompt: a.user_prompt,
            model: a.model,
            tools: a.tools,
            schedule: a.schedule
              ? {
                  cron: a.schedule.cron,
                  timezone: a.schedule.timezone,
                  is_paused: a.schedule.is_paused,
                }
              : null,
            a2a_enabled: a.a2a_enabled,
          }}
        />
      )}
    </Loaded>
  );
}
