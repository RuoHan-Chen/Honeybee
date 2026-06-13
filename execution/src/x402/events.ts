/**
 * In-memory pub/sub of agent economy events.
 *
 * Used to power:
 *   - SSE stream at GET /activity (UI live feed)
 *   - structured logs
 *
 * We keep this dead simple: a ring buffer + an EventEmitter. No persistence.
 * Restart the wallet service and the feed resets — that's fine for a demo.
 */
import { EventEmitter } from 'node:events';

export type ActivityKind =
  | 'x402.required'   // server sent a 402
  | 'x402.paid'       // client successfully paid + got 200
  | 'x402.verified'   // server verified payment + served response
  | 'attestation'     // on-chain attestation written
  | 'agent.action';   // generic agent step (loop tick, decision, etc.)

export interface Activity {
  id: string;
  ts: number;
  kind: ActivityKind;
  /** Who initiated. Always the agent label when known. */
  actor?: string;
  /** Target/counterparty. */
  counterparty?: string;
  /** Human-readable summary line for the UI ticker. */
  summary: string;
  /** Arbitrary structured payload (tx hash, amount, etc.). */
  details?: Record<string, unknown>;
}

const BUFFER_SIZE = 500;
const buffer: Activity[] = [];
export const events = new EventEmitter();
events.setMaxListeners(50);

export function emitActivity(a: Omit<Activity, 'id' | 'ts'> & { ts?: number }): Activity {
  const ev: Activity = {
    id: Math.random().toString(36).slice(2) + Date.now().toString(36),
    ts: a.ts ?? Date.now(),
    ...a,
  };
  buffer.push(ev);
  if (buffer.length > BUFFER_SIZE) buffer.shift();
  events.emit('activity', ev);
  return ev;
}

export function recentActivity(limit = 100): Activity[] {
  return buffer.slice(-limit).reverse();
}
