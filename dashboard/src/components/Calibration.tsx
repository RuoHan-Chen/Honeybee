import type { Position } from "../lib/api";
import { pct } from "../lib/format";

// Per-category calibration: of markets predicted at ~X%, how many resolved YES.
export function Calibration({ resolved }: { resolved: Position[] }) {
  const byCat = new Map<string, { color: string; preds: number[]; outcomes: number[] }>();
  for (const p of resolved) {
    const key = p.category_label;
    const g = byCat.get(key) ?? { color: p.category_color, preds: [], outcomes: [] };
    g.preds.push(p.predicted_fair_value ?? p.fair_value);
    g.outcomes.push(p.resolved_value ?? 0);
    byCat.set(key, g);
  }

  const rows = [...byCat.entries()].map(([cat, g]) => {
    const avgPred = g.preds.reduce((s, x) => s + x, 0) / g.preds.length;
    const yesRate = g.outcomes.reduce((s, x) => s + (x >= 0.5 ? 1 : 0), 0) / g.outcomes.length;
    return { cat, color: g.color, n: g.preds.length, avgPred, yesRate };
  });

  if (rows.length === 0) return null;

  return (
    <div className="card section">
      <h2 className="section-title">Calibration — predicted vs. actual</h2>
      <div className="calib-row head">
        <div>Category</div>
        <div>N</div>
        <div>Avg predicted</div>
        <div>Resolved YES</div>
      </div>
      {rows.map((r) => (
        <div className="calib-row" key={r.cat}>
          <div className="cat" style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <span className="dot" style={{ background: r.color }} />
            {r.cat}
          </div>
          <div className="muted">{r.n}</div>
          <div className="muted">{pct(r.avgPred)}</div>
          <div className="muted">{pct(r.yesRate)}</div>
        </div>
      ))}
    </div>
  );
}
