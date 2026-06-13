const API = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
const WALLET = process.env.NEXT_PUBLIC_WALLET_URL || 'http://127.0.0.1:8787';

export interface Agent {
  ens: string;
  label: string;
  wallet_id: string | null;
  wallet_address: string | null;
  bankroll_usd: number;
  kelly_fraction: number;
  confidence_floor: number;
  venue: string;
  llm_tier: string;
  x402_daily_usd: number;
  paused: number;
  created_at: number;
  fills_count?: number;
  notional_usd?: number;
  funded_usd?: number;
}

export interface Recommendation {
  rec_id: string;
  ts: number;
  agent_ens: string;
  user_address: string;
  venue: string;
  market_id: string;
  market_question: string;
  outcome: string;
  side: 'BUY' | 'SELL';
  fair_price: number;
  market_price: number;
  edge: number;
  confidence: number;
  suggested_size_usd: number;
  rationale: string;
  sources: string[];
  research_hash: string;
  research_attestation_tx: string | null;
  expires_at: number;
  status: 'pending' | 'approved' | 'rejected' | 'expired' | 'executed' | 'failed';
}

export interface Reputation {
  ens: string;
  recommendations: number;
  executed_trades: number;
  resolutions_anchored: number;
}

export interface MarketCandidate {
  venue: string;
  market_id: string;
  question: string;
  prices: Record<string, number>;
  volume_24h: number;
  uncertainty: number;
  score: number;
  url: string | null;
}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    cache: 'no-store',
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => j<{ ok: boolean; dry_run: boolean }>('/health'),

  listAgents: () => j<Agent[]>('/agents'),
  getAgent: (ens: string) => j<Agent>(`/agents/${encodeURIComponent(ens)}`),
  createAgent: (body: Partial<Agent>) =>
    j<Agent>('/agents', { method: 'POST', body: JSON.stringify(body) }),
  updateAgent: (ens: string, patch: Partial<Agent>) =>
    j<Agent>(`/agents/${encodeURIComponent(ens)}`, {
      method: 'PATCH', body: JSON.stringify(patch),
    }),
  reputation: (ens: string) => j<Reputation>(`/agents/${encodeURIComponent(ens)}/reputation`),

  topMarkets: () => j<MarketCandidate[]>('/markets/top'),

  hire: (body: {
    user_address: string;
    agent_ens: string;
    venue: string;
    market_id: string;
    price_usd?: number;
    tx_hash?: string;
  }) => j<Recommendation>('/research', { method: 'POST', body: JSON.stringify(body) }),

  listRecommendations: (opts: { user_address?: string; agent_ens?: string;
                                status?: Recommendation['status']; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(opts).forEach(([k, v]) => v !== undefined && qs.set(k, String(v)));
    return j<Recommendation[]>('/recommendations' + (qs.toString() ? `?${qs}` : ''));
  },
  approve: (rec_id: string, creds: Record<string, unknown> = {}) =>
    j<{ fill: any; attestation: any }>(
      `/recommendations/${encodeURIComponent(rec_id)}/approve`,
      { method: 'POST', body: JSON.stringify({ creds }) }
    ),
  reject: (rec_id: string) =>
    j<{ ok: boolean }>(`/recommendations/${encodeURIComponent(rec_id)}/reject`, { method: 'POST' }),

  pay: (body: {
    agent_ens: string; from_address: string; amount_usd: number;
    tx_hash?: string; kind?: 'fund' | 'hire' | 'x402';
  }) => j<{ ok: boolean }>('/pay', { method: 'POST', body: JSON.stringify(body) }),
};

// ─── Wallet service (TS, :8787) — fleet roster + activity feed ──────────
export interface FleetAgent {
  label: string;
  role: string;
  model: string;
  description: string;
  privyWalletId: string;
  address: `0x${string}`;
  node: `0x${string}`;
  explorer?: { address: string | null };
  ens?: {
    name: string;
    parent: string;
    resolvedAddress: `0x${string}` | null;
    verified: boolean;
    checkedAt: number;
    explorer: string;
  } | null;
}

export interface Activity {
  id: string;
  ts: number;
  kind: 'x402.required' | 'x402.paid' | 'x402.verified' | 'attestation' | 'agent.action';
  actor?: string;
  counterparty?: string;
  summary: string;
  details?: Record<string, unknown>;
}

export const walletApi = {
  baseUrl: WALLET,
  fleet: async (): Promise<FleetAgent[]> => {
    const r = await fetch(`${WALLET}/agents/fleet`, { cache: 'no-store' });
    if (!r.ok) throw new Error(`fleet ${r.status}`);
    return r.json();
  },
  recentActivity: async (): Promise<Activity[]> => {
    const r = await fetch(`${WALLET}/activity`, { cache: 'no-store' });
    if (!r.ok) throw new Error(`activity ${r.status}`);
    return r.json();
  },
  /** Returns an EventSource subscribed to the live activity feed. */
  streamActivity: (): EventSource => new EventSource(`${WALLET}/activity/stream`),
};
