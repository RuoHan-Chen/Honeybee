import { useState } from "react";
import type { Position } from "../lib/api";
import { cents, expiryLabel, micro, money, money0, pnlClass } from "../lib/format";
import { DecisionAudit } from "./DecisionAudit";

function Cell({ k, v, cls }: { k: string; v: React.ReactNode; cls?: string }) {
  return (
    <div className="cell">
      <div className="k">{k}</div>
      <div className={`v ${cls ?? ""}`}>{v}</div>
    </div>
  );
}

export function PositionCard({
  pos,
  defaultOpen = false,
  resolved = false,
}: {
  pos: Position;
  defaultOpen?: boolean;
  resolved?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const sideYes = pos.side === "BUY_YES";

  const pnl = resolved ? pos.realized_pnl ?? 0 : pos.unrealized_pnl;
  const pnlLabel = resolved ? "Realized P&L" : "Unrealized P&L";

  return (
    <div className="card">
      <div className="pos-head">
        <div>
          <div className="pos-meta">
            <span className="dot" style={{ background: pos.category_color }} />
            {pos.category_label}
            <span>·</span>
            <span>{expiryLabel(pos.expiry)}</span>
          </div>
          <div className="q">
            {pos.url ? (
              <a href={pos.url} target="_blank" rel="noreferrer">
                {pos.question}
              </a>
            ) : (
              pos.question
            )}
          </div>
        </div>
        <div className="pos-pnl">
          <div className={`v ${pnlClass(pnl)}`}>{money(pnl, { sign: true })}</div>
          <div className="l">{pnlLabel}</div>
        </div>
      </div>

      <div className="grid">
        <Cell
          k="Side"
          v={<span className={`side-tag ${sideYes ? "side-yes" : "side-no"}`}>{sideYes ? "Buy YES" : "Buy NO"}</span>}
        />
        <Cell k="Entry odds" v={cents(pos.entry_price)} />
        <Cell k="Fair price" v={cents(pos.fair_value)} cls="fair" />
        <Cell k="Edge" v={`${pos.edge_pts > 0 ? "+" : ""}${pos.edge_pts} pts`} cls={pnlClass(pos.edge_pts)} />
        <Cell k="Exposure" v={money0(pos.exposure_usd)} />
        <Cell k="Max payout" v={money0(pos.max_payout)} />
        {resolved ? (
          <>
            <Cell k="Predicted" v={cents(pos.predicted_fair_value ?? pos.fair_value)} cls="fair" />
            <Cell
              k="Resolved"
              v={(pos.resolved_value ?? 0) >= 0.5 ? "YES" : "NO"}
              cls={(pos.resolved_value ?? 0) >= 0.5 ? "pos" : "neg"}
            />
          </>
        ) : null}
      </div>

      <button className="audit-toggle" onClick={() => setOpen((o) => !o)}>
        <span>
          <span className={`chev ${open ? "open" : ""}`}>▸</span> Decision audit
        </span>
        <span className="cost">{micro(pos.decision_cost_usd)} to decide</span>
      </button>

      {open ? <DecisionAudit decisionId={pos.decision_id} /> : null}
    </div>
  );
}
