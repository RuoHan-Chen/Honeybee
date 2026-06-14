/**
 * Agent roster, sourced from var/agents.json (written by scripts/provision_agents.ts).
 *
 * This is the canonical mapping `label → {address, privyWalletId, node}`. Used by:
 *   - the x402 `/agent/:label/signal` route (looks up "who gets paid")
 *   - the pay-by-ENS path in /agent/pay (resolve label → addr)
 *   - the autonomous loop (find the analysts to consult)
 *   - the UI (render the fleet)
 */
import fs from 'node:fs';
import path from 'node:path';

export interface AgentRecord {
  label: string;
  role: string;
  model: string;
  description: string;
  privyWalletId: string;
  address: `0x${string}`;
  node: `0x${string}`;
}

let _cache: AgentRecord[] | null = null;
let _mtimeMs = 0;

function rosterPath(): string {
  return process.env.AGENTS_ROSTER_PATH ?? path.resolve(process.cwd(), 'var/agents.json');
}

export function loadRoster(): AgentRecord[] {
  const p = rosterPath();
  if (!fs.existsSync(p)) {
    _cache = [];
    return _cache;
  }
  const stat = fs.statSync(p);
  if (_cache && stat.mtimeMs === _mtimeMs) return _cache;
  const raw = JSON.parse(fs.readFileSync(p, 'utf8')) as { agents: AgentRecord[] };
  _cache = raw.agents;
  _mtimeMs = stat.mtimeMs;
  return _cache;
}

export function findAgent(labelOrAddr: string): AgentRecord | null {
  const roster = loadRoster();
  const lc = labelOrAddr.toLowerCase();
  return (
    roster.find((a) => a.label.toLowerCase() === lc) ??
    roster.find((a) => a.address.toLowerCase() === lc) ??
    null
  );
}
