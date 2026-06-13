import { useEffect, useState } from "react";
import { api, type DecisionAudit as Audit } from "../lib/api";
import { micro, pnlClass, relativeTime, signed } from "../lib/format";

function AcquisitionChip({ method, cost }: { method: string; cost: number }) {
  const paid = cost > 0 || method.includes("paid") || method.includes("x402");
  const label = paid ? `${method.replace("_", " ")} · ${micro(cost)}` : "free";
  return <span className={`chip ${paid ? "paid" : ""}`}>{label}</span>;
}

function datapointsLine(dp: Record<string, unknown>): string {
  const parts = Object.entries(dp).map(([k, v]) => `${k}=${JSON.stringify(v)}`);
  return parts.join("  ");
}

export function DecisionAudit({ decisionId }: { decisionId: string }) {
  const [audit, setAudit] = useState<Audit | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .decision(decisionId)
      .then((a) => alive && setAudit(a))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [decisionId]);

  if (error) return <div className="loading">Failed to load audit: {error}</div>;
  if (!audit) return <div className="loading">Loading decision audit…</div>;

  const r = audit.research;
  const risk = audit.risk;

  return (
    <div className="audit">
      {/* ── Research ─────────────────────────────────────────────── */}
      {r ? (
        <div className="block">
          <div className="block-head">
            <span className="title">Research agent</span>
            <span className="hmeta">
              {r.prior_fair_value.toFixed(2)} → <b>{r.fair_value.toFixed(2)}</b> · conf{" "}
              {r.confidence.toFixed(2)} · {r.model} · {micro(r.llm_cost_usd)}
            </span>
          </div>
          <div className="block-body">
            <p className="rationale">{r.rationale}</p>
            {r.source_attributions.map((a, i) => (
              <div className="src-row" key={i}>
                <div className="main">
                  <div className="name">
                    {a.url ? (
                      <a href={a.url} target="_blank" rel="noreferrer">
                        {a.source_name}
                      </a>
                    ) : (
                      a.source_name
                    )}
                  </div>
                  <div className="note">{a.note}</div>
                </div>
                <span className={`delta ${pnlClass(a.fair_value_delta)}`}>
                  {signed(a.fair_value_delta)}
                </span>
                <AcquisitionChip method={a.acquisition_method} cost={a.cost_usd} />
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* ── Data ─────────────────────────────────────────────────── */}
      <div className="block">
        <div className="block-head">
          <span className="title">Data agent</span>
          <span className="hmeta">total data cost {micro(audit.data.total_cost_usd)}</span>
        </div>
        <div className="block-body">
          {audit.data.sources.length === 0 ? (
            <div className="note">No external data sources used.</div>
          ) : (
            audit.data.sources.map((s, i) => (
              <div className="src-row" key={i}>
                <div className="main">
                  <div className="name">
                    {s.url ? (
                      <a href={s.url} target="_blank" rel="noreferrer">
                        {s.source_name}
                      </a>
                    ) : (
                      s.source_name
                    )}
                  </div>
                  <div className="dp">{datapointsLine(s.datapoints)}</div>
                </div>
                <AcquisitionChip method={s.acquisition_method} cost={s.cost_usd} />
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── Execution & risk ─────────────────────────────────────── */}
      {risk ? (
        <div className="block">
          <div className="block-head">
            <span className="title">Execution &amp; risk</span>
            <span className="hmeta">{risk.executed ? "executed" : "not executed"}</span>
          </div>
          <div className="block-body">
            <div className="sizing-sentence">
              market <b>{risk.market_price.toFixed(2)}</b> → fair <b>{risk.fair_value.toFixed(2)}</b>{" "}
              → edge <b>{(risk.edge * 100).toFixed(1)}pts</b> → Kelly size{" "}
              <b>${risk.size_usd.toFixed(2)}</b> @ limit <b>{risk.limit_price.toFixed(2)}</b>
              {risk.slippage_estimate > 0 ? <> · slippage est {(risk.slippage_estimate * 100).toFixed(1)}%</> : null}
            </div>
            <div className="checks">
              {risk.checks.map((c) => (
                <span key={c.name} className={`check ${c.passed ? "ok" : "fail"}`}>
                  {c.passed ? "✓" : "✗"} {c.name.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {/* ── Footer ───────────────────────────────────────────────── */}
      <div className="audit-footer">
        <span>{audit.decision_id}</span>
        <span>{relativeTime(audit.created_at)}</span>
        <span>
          reasoning {micro(audit.cost_breakdown.reasoning_usd)} + data{" "}
          {micro(audit.cost_breakdown.data_usd)} = <b>{micro(audit.total_cost_usd)}</b>
        </span>
      </div>
    </div>
  );
}
