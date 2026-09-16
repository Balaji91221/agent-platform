/** Every backend call the UI makes, typed and validated. */
import { z } from 'zod';
import { BASE_URL, request } from './client';
import type { Result } from './client';
import {
  agentSchema,
  deploymentSchema,
  connectionSchema,
  meSchema,
  healthSchema,
  mcpServerSchema,
  modelSchema,
  notificationSchema,
  postMessageResultSchema,
  prefsSchema,
  runLogSchema,
  runSchema,
  statsSchema,
  teamSchema,
  teamMessageSchema,
  toolCatalogueSchema,
  builderResultSchema,
} from './schemas';
import type {
  Agent,
  Deployment,
  BuilderResult,
  Connection,
  Me,
  Health,
  McpServer,
  Model,
  Notification,
  PostMessageResult,
  Prefs,
  Run,
  RunLog,
  Stats,
  Team,
  TeamMessage,
  ToolCatalogueEntry,
  ToolGrant,
} from './schemas';

const nothing = z.unknown().transform(() => undefined as void);
const s = (signal?: AbortSignal) => ({ signal });

/* ------------------------------------------------------------------ agents */

export type AgentInput = {
  name: string;
  description?: string;
  system_prompt?: string;
  user_prompt?: string;
  model?: string;
  tools?: ToolGrant[];
  schedule?: { cron: string; timezone: string; is_paused?: boolean } | null;
};

export const listAgents = (signal?: AbortSignal): Promise<Result<Agent[]>> =>
  request('/agents', z.array(agentSchema), s(signal));

export const getAgent = (id: number, signal?: AbortSignal): Promise<Result<Agent>> =>
  request(`/agents/${id}`, agentSchema, s(signal));

export const createAgent = (body: AgentInput): Promise<Result<Agent>> =>
  request('/agents', agentSchema, { method: 'POST', body });

export const updateAgent = (id: number, body: Partial<AgentInput>): Promise<Result<Agent>> =>
  request(`/agents/${id}`, agentSchema, { method: 'PATCH', body });

export const deleteAgent = (id: number): Promise<Result<void>> =>
  request(`/agents/${id}`, nothing, { method: 'DELETE' });

export const runAgent = (id: number): Promise<Result<Run>> =>
  request(`/agents/${id}/run`, runSchema, { method: 'POST' });

export const pauseAgent = (id: number): Promise<Result<Agent>> =>
  request(`/agents/${id}/pause`, agentSchema, { method: 'POST' });

export const resumeAgent = (id: number): Promise<Result<Agent>> =>
  request(`/agents/${id}/resume`, agentSchema, { method: 'POST' });

export const listAgentRuns = (id: number, signal?: AbortSignal): Promise<Result<Run[]>> =>
  request(`/agents/${id}/runs`, z.array(runSchema), s(signal));

export const getDeployment = (id: number, signal?: AbortSignal): Promise<Result<Deployment>> =>
  request(`/agents/${id}/deployment`, deploymentSchema, s(signal));

export const deployAgent = (id: number): Promise<Result<Deployment>> =>
  request(`/agents/${id}/deploy`, deploymentSchema, { method: 'POST' });

/* -------------------------------------------------------------------- runs */

export const getRun = (id: number, signal?: AbortSignal): Promise<Result<Run>> =>
  request(`/runs/${id}`, runSchema, s(signal));

export const getRunLogs = (id: number, signal?: AbortSignal): Promise<Result<RunLog[]>> =>
  request(`/runs/${id}/logs`, z.array(runLogSchema), s(signal));

/* ------------------------------------------------------------------ models */

export const listModels = (signal?: AbortSignal): Promise<Result<Model[]>> =>
  request('/models', z.array(modelSchema), s(signal));

export const listTools = (signal?: AbortSignal): Promise<Result<ToolCatalogueEntry[]>> =>
  request('/connections/tools', z.array(toolCatalogueSchema), s(signal));

/* ------------------------------------------------------------- connections */

export const listConnections = (signal?: AbortSignal): Promise<Result<Connection[]>> =>
  request('/connections', z.array(connectionSchema), s(signal));

export const addConnection = (body: {
  kind: 'api_key' | 'custom_http';
  provider: string;
  label?: string;
  secret: string;
  base_url?: string;
  auth_header?: string;
}): Promise<Result<Connection>> =>
  request('/connections', connectionSchema, { method: 'POST', body });

export const deleteConnection = (id: number): Promise<Result<void>> =>
  request(`/connections/${id}`, nothing, { method: 'DELETE' });

const oauthStartSchema = z.object({ provider: z.string(), authorize_url: z.string().url() });

/** 422 with the env var names when the backend has no OAuth client for the provider. */
export const oauthStart = (provider: string): Promise<Result<{ authorize_url: string }>> =>
  request(`/connections/oauth/${provider}/start`, oauthStartSchema);

/* --------------------------------------------------------------- mcp servers */

export const listMcpServers = (signal?: AbortSignal): Promise<Result<McpServer[]>> =>
  request('/mcp-servers', z.array(mcpServerSchema), s(signal));

export const addMcpServer = (body: {
  url: string;
  auth_kind: 'oauth' | 'bearer' | 'none';
  token?: string;
}): Promise<Result<McpServer>> =>
  request('/mcp-servers', mcpServerSchema, { method: 'POST', body });

export const rehandshakeMcpServer = (id: number): Promise<Result<McpServer>> =>
  request(`/mcp-servers/${id}/handshake`, mcpServerSchema, { method: 'POST' });

export const deleteMcpServer = (id: number): Promise<Result<void>> =>
  request(`/mcp-servers/${id}`, nothing, { method: 'DELETE' });

/* -------------------------------------------------------------------- team */

export const getTeam = (signal?: AbortSignal): Promise<Result<Team>> =>
  request('/team', teamSchema, s(signal));

export const addTeammate = (body: {
  agent_id: number;
  display_name: string;
  job_title: string;
  description?: string;
  colour?: string;
  make_lead?: boolean;
}): Promise<Result<unknown>> => request('/team/teammates', z.unknown(), { method: 'POST', body });

export const removeTeammate = (id: number): Promise<Result<void>> =>
  request(`/team/teammates/${id}`, nothing, { method: 'DELETE' });

export type TeammatePatch = {
  display_name?: string;
  job_title?: string;
  description?: string;
  colour?: string;
};

export const updateTeammate = (id: number, body: TeammatePatch): Promise<Result<unknown>> =>
  request(`/team/teammates/${id}`, z.unknown(), { method: 'PATCH', body });

export const setLead = (teammateId: number | null): Promise<Result<Team>> =>
  request('/team/lead', teamSchema, { method: 'PUT', body: { teammate_id: teammateId } });

export const getThread = (signal?: AbortSignal): Promise<Result<TeamMessage[]>> =>
  request('/team/messages', z.array(teamMessageSchema), s(signal));

export const postTeamMessage = (text: string): Promise<Result<PostMessageResult>> =>
  request('/team/messages', postMessageResultSchema, { method: 'POST', body: { text } });

export const clearThread = (): Promise<Result<void>> =>
  request('/team/messages', nothing, { method: 'DELETE' });

/* ----------------------------------------------------------- notifications */

export const listNotifications = (signal?: AbortSignal): Promise<Result<Notification[]>> =>
  request('/notifications', z.array(notificationSchema), s(signal));

export const markAllRead = (): Promise<Result<unknown>> =>
  request('/notifications/read-all', z.unknown(), { method: 'POST' });

export const markRead = (id: number): Promise<Result<unknown>> =>
  request(`/notifications/${id}/read`, z.unknown(), { method: 'POST' });

/** Where a notification leads: the agent page with that run pinned. */
export const notificationHref = (n: Notification): string =>
  n.agent_id === null || n.agent_id === undefined
    ? '/notifications'
    : `/agents/${n.agent_id}${n.run_id === null ? '' : `?run=${n.run_id}`}`;

export const getPrefs = (signal?: AbortSignal): Promise<Result<Prefs>> =>
  request('/notifications/prefs', prefsSchema, s(signal));

export const putPrefs = (body: Prefs): Promise<Result<Prefs>> =>
  request('/notifications/prefs', prefsSchema, { method: 'PUT', body });

/* ------------------------------------------------------------------- stats */

export const getStats = (
  range: 'today' | '7d' | '30d',
  signal?: AbortSignal,
): Promise<Result<Stats>> => request(`/stats?range=${range}`, statsSchema, s(signal));

/* ----------------------------------------------------------------- builder */

export type DraftTurn = { role: 'user' | 'assistant'; text: string };

/**
 * The browser's zone rides along so "9am" lands in the user's day, not UTC's,
 * and the last turns so a follow-up ("and post it to Slack") makes sense.
 */
export const buildDraft = (
  text: string,
  history: DraftTurn[] = [],
): Promise<Result<BuilderResult>> =>
  request('/builder/draft', builderResultSchema, {
    method: 'POST',
    body: { text, timezone: browserTimezone(), history: history.slice(-12) },
  });

/** Chrome still reports some legacy aliases; the form's zone list uses the current names. */
const LEGACY_ZONES: Record<string, string> = {
  'Asia/Calcutta': 'Asia/Kolkata',
  'Asia/Saigon': 'Asia/Ho_Chi_Minh',
  'Asia/Katmandu': 'Asia/Kathmandu',
  'Asia/Rangoon': 'Asia/Yangon',
  'Europe/Kiev': 'Europe/Kyiv',
};

function browserTimezone(): string | undefined {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone ? (LEGACY_ZONES[zone] ?? zone) : undefined;
  } catch {
    return undefined;
  }
}

/* -------------------------------------------------------------------- auth */

export const getMe = (signal?: AbortSignal): Promise<Result<Me>> =>
  request('/auth/me', meSchema, s(signal));

export const logout = (): Promise<Result<void>> =>
  request('/auth/logout', nothing, { method: 'POST' });

/** A plain link target: the backend redirects the browser to Google. */
export const loginUrl = (): string => `${BASE_URL}/auth/google/start`;

/* ------------------------------------------------------------------ system */

export const getHealth = (signal?: AbortSignal): Promise<Result<Health>> =>
  request('/health', healthSchema, s(signal));
