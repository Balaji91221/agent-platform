/**
 * App-local types. Everything that crosses the network is defined by a zod
 * schema in `lib/api/schemas.ts` instead, so there is one source of truth.
 */

export type MateState = 'idle' | 'working' | 'blocked';
