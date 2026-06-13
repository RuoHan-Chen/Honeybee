import type { ExposureRow } from "../lib/api";
import { money, money0, pnlClass } from "../lib/format";

export function ExposureBar({ rows }: { rows: ExposureRow[] }) {
  const total = rows.reduce((s, r) => s + r.exposure_usd, 0) || 1;

  return (
    <div className="card">
      <div className="exposure-bar">
        {rows.map((r) => (
          <div
            key={r.vertical}
            className="seg"
            style={{ width: `${(r.exposure_usd / total) * 100}%`, background: r.color }}
            title={`${r.category}: ${money0(r.exposure_usd)}`}
          />
        ))}
      </div>

      <div className="exposure-list">
        {rows.map((r) => (
          <div className="exposure-row" key={r.vertical}>
            <div className="cat">
              <span className="dot" style={{ background: r.color }} />
              {r.category}
            </div>
            <div className="muted">{money0(r.exposure_usd)}</div>
            <div className="muted">{r.positions} pos</div>
            <div className={pnlClass(r.pnl)}>{money(r.pnl, { sign: true })}</div>
          </div>
        ))}
        {rows.length === 0 ? <div className="empty">No open exposure</div> : null}
      </div>
    </div>
  );
}
