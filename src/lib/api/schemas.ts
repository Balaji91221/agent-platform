/**
 * Every shape the backend can send.
 *
 * Data crossing the network is `unknown` until it is parsed here — these
 * schemas are the single place that turns it into a real type, so nothing
 * downstream needs a cast.
 */
import { z } from 'zod';

export const toolGrantSchema = z.object({
  tool_name: z.string(),
  can_write: z.boolean(),
});

export const scheduleSchema = z.object({
  cron: z.string(),
  timezone: z.string(),
  is_paused: z.boolean(),
  next_due_at: z.string().nullable().optional(),
  words: z.string().default(''),
  next_runs: z.array(z.string()).default([]),
});

export const agentSchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string(),
  system_prompt: z.string(),
  user_prompt: z.string(),
  model: z.string(),
  is_running: z.boolean(),
  a2a_enabled: z.boolean().default(false),
  created_at: z.string(),
  tools: z.array(toolGrantSchema).default([]),
  schedule: scheduleSchema.nullable().optional(),
});

export const runSchema = z.object({
  id: z.number(),
  agent_id: z.number(),
  trigger: z.string(),
  status: z.string(),
  attempt: z.number(),
  started_at: z.string().nullable(),
  ended_at: z.string().nullable(),
  duration_seconds: z.number().nullable(),
  output: z.string().nullable(),
  error: z.string().nullable(),
  created_at: z.string(),
});

export const runLogSchema = z.object({
  seq: z.number(),
  at: z.string(),
  kind: z.string(),
  line: z.string(),
});

/** One line off the SSE stream: a log row, or the terminal marker. */
export const streamEventSchema = z.union([
  runLogSchema,
  z.object({ event: z.literal('done'), status: z.string() }),
  z.object({ event: z.literal('timeout') }),
]);

export const modelSchema = z.object({
  name: z.string(),
  provider: z.string(),
  catalogue_id: z.string(),
  vision: z.boolean(),
  reasoning: z.boolean(),
});

export const toolCatalogueSchema = z.object({
  name: z.string(),
  description: z.string(),
  writes: z.boolean(),
  provider: z.string(),
});

export const connectionSchema = z.object({
  id: z.number(),
  kind: z.string(),
  provider: z.string(),
  label: z.string(),
  status: z.string(),
  created_at: z.string(),
});

export const mcpServerSchema = z.object({
  id: z.number(),
  name: z.string(),
  url: z.string(),
  auth_kind: z.string(),
  status: z.string(),
  tools_json: z.array(z.unknown()).default([]),
  last_handshake_at: z.string().nullable(),
  error: z.string().nullable(),
});

export const mcpToolSchema = z.object({
  name: z.string(),
  description: z.string().optional().default(''),
});

export const teammateSchema = z.object({
  id: z.number(),
  agent_id: z.number(),
  display_name: z.string(),
  job_title: z.string(),
  description: z.string(),
  colour: z.string(),
  is_lead: z.boolean(),
  is_running: z.boolean(),
  agent_name: z.string(),
});

export const teamSchema = z.object({
  id: z.number(),
  lead_teammate_id: z.number().nullable(),
  teammates: z.array(teammateSchema).default([]),
});

export const teamMessageSchema = z.object({
  id: z.number(),
  kind: z.string(),
  from_teammate_id: z.number().nullable(),
  to_teammate_id: z.number().nullable(),
  text: z.string(),
  run_id: z.number().nullable(),
  at: z.string(),
});

export const postMessageResultSchema = z.object({
  route: z.string(),
  teammate_id: z.number().nullable().optional(),
  reason: z.string().optional(),
});

export const notificationSchema = z.object({
  id: z.number(),
  kind: z.string(),
  title: z.string(),
  body: z.string(),
  run_id: z.number().nullable(),
  agent_id: z.number().nullable().optional(),
  agent_name: z.string().default(''),
  is_read: z.boolean(),
  at: z.string(),
});

export const prefsSchema = z.object({
  email_on: z.boolean(),
  slack_dm_on: z.boolean(),
  webhook_on: z.boolean(),
  webhook_url: z.string().nullable(),
  quiet_from: z.string().nullable(),
  quiet_to: z.string().nullable(),
  notify_on_success: z.boolean(),
  /** Read-only: where email is actually sent. */
  email_to: z.string().default(''),
});

export const statsSchema = z.object({
  agents_used: z.number(),
  agent_limit: z.number(),
  runs_today: z.number(),
  runs_total: z.number(),
  success_rate: z.number(),
  median_duration_seconds: z.number().nullable(),
  failures_this_week: z.number(),
  runs_per_hour: z.array(z.object({ hour: z.number(), runs: z.number() })),
  outcomes: z.object({
    succeeded: z.number(),
    retried_then_passed: z.number(),
    failed: z.number(),
  }),
  busiest_agents: z.array(z.object({ name: z.string(), runs: z.number() })),
});

export const agentDraftSchema = z.object({
  name: z.string(),
  description: z.string(),
  system_prompt: z.string(),
  user_prompt: z.string(),
  model: z.string(),
  cron: z.string(),
  timezone: z.string(),
  tools: z.array(z.string()).default([]),
});

export type ToolGrant = z.infer<typeof toolGrantSchema>;
export type Schedule = z.infer<typeof scheduleSchema>;
export type Agent = z.infer<typeof agentSchema>;
export type Run = z.infer<typeof runSchema>;
export type RunLog = z.infer<typeof runLogSchema>;
export type StreamEvent = z.infer<typeof streamEventSchema>;
export type Model = z.infer<typeof modelSchema>;
export type ToolCatalogueEntry = z.infer<typeof toolCatalogueSchema>;
export type Connection = z.infer<typeof connectionSchema>;
export type McpServer = z.infer<typeof mcpServerSchema>;
export type Teammate = z.infer<typeof teammateSchema>;
export type Team = z.infer<typeof teamSchema>;
export type TeamMessage = z.infer<typeof teamMessageSchema>;
export type PostMessageResult = z.infer<typeof postMessageResultSchema>;
export type Notification = z.infer<typeof notificationSchema>;
export type Prefs = z.infer<typeof prefsSchema>;
export type Stats = z.infer<typeof statsSchema>;
/** The builder either answers in words or hands back a draft. */
export const builderResultSchema = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('reply'), text: z.string() }),
  z.object({ kind: z.literal('draft'), draft: agentDraftSchema }),
]);

export type AgentDraft = z.infer<typeof agentDraftSchema>;
export type BuilderResult = z.infer<typeof builderResultSchema>;

export const meSchema = z.object({
  id: z.number(),
  email: z.string(),
  name: z.string().nullable(),
  picture: z.string().nullable(),
});
export type Me = z.infer<typeof meSchema>;

export const limitsSchema = z.object({
  max_attempts: z.number(),
  retry_backoff_seconds: z.array(z.number()),
  run_timeout_seconds: z.number(),
  max_tool_calls_per_run: z.number(),
  tool_call_timeout_seconds: z.number(),
  max_agents_per_user: z.number(),
});
export type Limits = z.infer<typeof limitsSchema>;

export const healthSchema = z.object({
  status: z.string(),
  version: z.string(),
  model_provider: z.string(),
  builder_model: z.string(),
  db: z.string(),
  redis: z.string(),
  limits: limitsSchema,
});
export type Health = z.infer<typeof healthSchema>;

/** One Jenkins build. `status` is the only field the UI switches on. */
export const jobRunSchema = z.object({
  job: z.string(),
  status: z.enum([
    'none',
    'queued',
    'running',
    'success',
    'failure',
    'unavailable',
    'disabled',
  ]),
  build_number: z.number().nullable(),
  url: z.string().nullable(),
  message: z.string(),
});
export type JobRun = z.infer<typeof jobRunSchema>;
export type JobStatus = JobRun['status'];

/** How another agent reaches this one. `token` is a bearer credential. */
export const a2aSchema = z.object({
  /** Effective: the server switch and the agent's own switch are both on. */
  enabled: z.boolean(),
  server_enabled: z.boolean(),
  agent_enabled: z.boolean(),
  card_url: z.string(),
  endpoint_url: z.string(),
  token: z.string(),
});
export type A2A = z.infer<typeof a2aSchema>;

export const deploymentSchema = z.object({
  agent_id: z.number(),
  slug: z.string(),
  host_entry: z.string(),
  hosts_file: z.string(),
  enabled: z.boolean(),
  jobs: z.array(jobRunSchema),
  a2a: a2aSchema,
});
export type Deployment = z.infer<typeof deploymentSchema>;
