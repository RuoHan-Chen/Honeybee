import type { Summary } from "../lib/api";
import { money, money0, pnlClass } from "../lib/format";

function Kpi({ label, value, cls, meta }: { label: string; value: string; cls?: string; meta?: string }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className={`value ${cls ?? ""}`}>{value}</div>
      {meta ? <div className="meta">{meta}</div> : null}
    </div>
  );
}

export function KpiRow({ summary }: { summary: Summary | null }) {
  if (!summary) return null;
  return (
    <div className="kpi-grid">
      <Kpi label="Net P&L" value={money(summary.net_pnl, { sign: true })} cls={pnlClass(summary.net_pnl)} />
      <Kpi label="Realized" value={money(summary.realized_pnl, { sign: true })} cls={pnlClass(summary.realized_pnl)} />
      <Kpi label="Unrealized" value={money(summary.unrealized_pnl, { sign: true })} cls={pnlClass(summary.unrealized_pnl)} />
      <Kpi
        label="Open exposure"
        value={money0(summary.open_exposure_usd)}
        meta={`${summary.open_positions} positions · ${summary.categories_count} categories`}
      />
    </div>
  );
}
