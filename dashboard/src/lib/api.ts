// Typed fetchers + interfaces mirroring the confirmed FastAPI endpoint shapes.

export interface Summary {
  status: "live" | "paused";
  bankroll: number;
  net_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  open_exposure_usd: number;
  open_positions: number;
  categories_count: number;
  agent: { ens: string; wallet: string; settling_on: string };
}

export interface ExposureRow {
  category: string;
  vertical: string;
  color: string;
  exposure_usd: number;
  positions: number;
  pnl: number;
}

export interface Position {
  market_id: string;
  decision_id: string;
  question: string;
  category: string;
  vertical: string;
  url: string;
  side: "BUY_YES" | "BUY_NO";
  entry_price: number;
  fair_value: number;
  edge_pts: number;
  exposure_usd: number;
  max_payout: number;
  expiry: string | null;
  unrealized_pnl: number;
  decision_cost_usd: number;
  category_label: string;
  category_color: string;
  // resolved-only
  resolved_value?: number;
  realized_pnl?: number;
  predicted_fair_value?: number;
  was_calibrated?: boolean;
}

export interface SourceAttribution {
  source_name: string;
  url: string;
  note: string;
  fair_value_delta: number;
  acquisition_method: string;
  cost_usd: number;
}

export interface DataSource {
  source_name: string;
  url: string;
  source_type: string;
  acquisition_method: string;
  cost_usd: number;
  datapoints: Record<string, unknown>;
}

export interface RiskCheck { name: string; passed: boolean; }

export interface DecisionAudit {
  decision_id: string;
  research: {
    model: string;
    confidence: number;
    prior_fair_value: number;
    fair_value: number;
    rationale: string;
    llm_cost_usd: number;
    source_attributions: SourceAttribution[];
  } | null;
  data: { total_cost_usd: number; sources: DataSource[] };
  risk: {
    market_price: number;
    fair_value: number;
    edge: number;
    kelly_inputs: Record<string, number>;
    size_usd: number;
    limit_price: number;
    slippage_estimate: number;
    side: string;
    executed: boolean;
    checks: RiskCheck[];
  } | null;
  trail_events: { agent: string; timestamp: string; text: string }[];
  cost_breakdown: { reasoning_usd: number; data_usd: number };
  total_cost_usd: number;
  created_at: string | null;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`);
  return r.json() as Promise<T>;
}

export const api = {
  summary: () => get<Summary>("/api/summary"),
  exposure: () => get<ExposureRow[]>("/api/exposure"),
  positions: (status: "open" | "resolved") =>
    get<Position[]>(`/api/positions?status=${status}`),
  decision: (id: string) => get<DecisionAudit>(`/api/decisions/${id}`),
};
