"""Read-only dashboard API.

A thin FastAPI app that exposes the Repository as JSON. It depends ONLY on the
Repository interface, so it works against SqliteRepository today and any future
backend unchanged. It never writes and never places trades.

Run:  uvicorn src.api.app:app --reload --port 8000
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from ..store.repository import (
    FillRecord,
    MarketRecord,
    OutcomeRecord,
    Repository,
    ResearchRecord,
    RiskDecisionRecord,
)
from ..store.factory import build_repository

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")
_MANDATE_PATH = _ROOT / "config" / "mandate.yaml"

_LIVE_WINDOW = timedelta(minutes=5)

# vertical → display label + color dot (stable buckets, per confirmed decision)
_VERTICAL_META: dict[str, dict[str, str]] = {
    "sports":   {"label": "Sports",   "color": "#3b82f6"},
    "politics": {"label": "Politics", "color": "#a855f7"},
    "macro":    {"label": "Macro",    "color": "#14b8a6"},
    "weather":  {"label": "Weather",  "color": "#f59e0b"},
    "other":    {"label": "Other",    "color": "#94a3b8"},
}


def _load_mandate() -> dict:
    try:
        with open(_MANDATE_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _round(x: float | None, n: int = 2) -> float:
    return round(float(x or 0.0), n)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Dashboard:
    """Assembles dashboard views from the Repository. Pure reads."""

    def __init__(self, repo: Repository, mandate: dict) -> None:
        self.repo = repo
        self.mandate = mandate

    # ── position assembly ─────────────────────────────────────────────────────

    async def _current_price(self, market: MarketRecord | None, side: str) -> float:
        """Latest mark for the held side (BUY_YES→yes_price, BUY_NO→no_price)."""
        if market is None:
            return 0.0
        return market.no_price if side == "BUY_NO" else market.yes_price

    def _entry_price(self, fill: FillRecord | None, risk: RiskDecisionRecord) -> float:
        if fill is not None and fill.avg_price > 0:
            return fill.avg_price
        return risk.market_price

    def _exposure(self, fill: FillRecord | None, risk: RiskDecisionRecord) -> float:
        if fill is not None and fill.size_usd > 0:
            return fill.size_usd
        return risk.size_usd

    async def _position_summary(
        self, risk: RiskDecisionRecord, fill: FillRecord | None,
        outcome: OutcomeRecord | None,
    ) -> dict:
        market = await self.repo.get_market(risk.market_id)
        research = await self.repo.get_research(risk.decision_id)

        entry_price = self._entry_price(fill, risk)
        exposure = self._exposure(fill, risk)
        fair_value = research.fair_value if research else risk.fair_value
        edge_pts = round((fair_value - entry_price) * 100)
        max_payout = round(exposure / entry_price) if entry_price > 0 else 0
        current_price = await self._current_price(market, risk.side)

        # unrealized: shares = exposure/entry; current value = shares*current; pnl = value - exposure
        shares = exposure / entry_price if entry_price > 0 else 0.0
        unrealized = shares * current_price - exposure

        decision_cost = await self._decision_cost(risk.decision_id)

        summary = {
            "market_id": risk.market_id,
            "decision_id": risk.decision_id,
            "question": market.question if market else "",
            "category": market.category if market else "",
            "vertical": market.vertical if market else "other",
            "url": market.url if market else "",
            "side": risk.side,
            "entry_price": _round(entry_price, 4),
            "fair_value": _round(fair_value, 4),
            "edge_pts": edge_pts,
            "exposure_usd": _round(exposure),
            "max_payout": max_payout,
            "expiry": _as_aware(market.end_date).isoformat() if market and market.end_date else None,
            "unrealized_pnl": _round(unrealized),
            "decision_cost_usd": _round(decision_cost, 5),
        }
        if outcome is not None:
            summary.update({
                "resolved_value": _round(outcome.resolved_value, 4),
                "realized_pnl": _round(outcome.realized_pnl),
                "predicted_fair_value": _round(fair_value, 4),
                "was_calibrated": outcome.was_calibrated,
            })
        return summary

    async def _decision_cost(self, decision_id: str) -> float:
        research = await self.repo.get_research(decision_id)
        llm = research.token_cost_usd if research else 0.0
        data_uses = await self.repo.get_data_source_uses(decision_id)
        data_cost = sum(u.cost_usd for u in data_uses)
        return llm + data_cost

    async def _executed_decisions(self) -> list[tuple[RiskDecisionRecord, FillRecord]]:
        fills = await self.repo.list_fills()
        out = []
        for f in fills:
            risk = await self.repo.get_risk_decision(f.decision_id)
            if risk is not None:
                out.append((risk, f))
        return out

    # ── endpoints ──────────────────────────────────────────────────────────────

    async def summary(self) -> dict:
        executed = await self._executed_decisions()
        outcomes = {o.decision_id: o for o in await self.repo.list_outcomes()}

        realized = sum(o.realized_pnl for o in outcomes.values())
        unrealized = 0.0
        open_exposure = 0.0
        open_count = 0
        categories: set[str] = set()

        for risk, fill in executed:
            if fill.decision_id in outcomes:
                continue  # resolved
            ps = await self._position_summary(risk, fill, None)
            unrealized += ps["unrealized_pnl"]
            open_exposure += ps["exposure_usd"]
            open_count += 1
            categories.add(ps["vertical"])

        bankroll = float(self.mandate.get("bankroll_usd", 0))
        latest_ts = _as_aware(await self.repo.get_latest_trail_timestamp())
        status = "live" if latest_ts and (_now() - latest_ts) < _LIVE_WINDOW else "paused"

        return {
            "status": status,
            "bankroll": _round(bankroll),
            "net_pnl": _round(realized + unrealized),
            "realized_pnl": _round(realized),
            "unrealized_pnl": _round(unrealized),
            "open_exposure_usd": _round(open_exposure),
            "open_positions": open_count,
            "categories_count": len(categories),
            "agent": {
                "ens": os.getenv("ENS_NAME", "") or os.getenv("ENS_AGENT_LABEL", ""),
                "wallet": os.getenv("WALLET_ADDRESS", ""),
                "settling_on": "Polygon",
            },
        }

    async def exposure(self) -> list[dict]:
        executed = await self._executed_decisions()
        outcomes = {o.decision_id for o in await self.repo.list_outcomes()}

        groups: dict[str, dict] = {}
        for risk, fill in executed:
            if fill.decision_id in outcomes:
                continue
            ps = await self._position_summary(risk, fill, None)
            vert = ps["vertical"]
            g = groups.setdefault(vert, {"exposure_usd": 0.0, "positions": 0, "pnl": 0.0})
            g["exposure_usd"] += ps["exposure_usd"]
            g["positions"] += 1
            g["pnl"] += ps["unrealized_pnl"]

        out = []
        for vert, g in groups.items():
            meta = _VERTICAL_META.get(vert, _VERTICAL_META["other"])
            out.append({
                "category": meta["label"],
                "vertical": vert,
                "color": meta["color"],
                "exposure_usd": _round(g["exposure_usd"]),
                "positions": g["positions"],
                "pnl": _round(g["pnl"]),
            })
        out.sort(key=lambda x: x["exposure_usd"], reverse=True)
        return out

    async def positions(self, status: str) -> list[dict]:
        executed = await self._executed_decisions()
        outcomes = {o.decision_id: o for o in await self.repo.list_outcomes()}

        out = []
        for risk, fill in executed:
            outcome = outcomes.get(fill.decision_id)
            is_resolved = outcome is not None
            if status == "open" and is_resolved:
                continue
            if status == "resolved" and not is_resolved:
                continue
            ps = await self._position_summary(risk, fill, outcome)
            # attach vertical display meta
            meta = _VERTICAL_META.get(ps["vertical"], _VERTICAL_META["other"])
            ps["category_label"] = meta["label"]
            ps["category_color"] = meta["color"]
            out.append(ps)
        return out

    async def decision(self, decision_id: str) -> dict:
        risk = await self.repo.get_risk_decision(decision_id)
        research = await self.repo.get_research(decision_id)
        if risk is None and research is None:
            raise HTTPException(status_code=404, detail="decision not found")

        trail = await self.repo.get_decision_trail(decision_id)
        data_uses = await self.repo.get_data_source_uses(decision_id)
        attributions = await self.repo.get_source_attributions(decision_id)

        # index data uses by source_name for enriching attributions
        use_by_name = {u.source_name: u for u in data_uses}

        # ── research block ─────────────────────────────────────────────────────
        research_block = None
        if research is not None:
            enriched_attrs = []
            for a in attributions:
                u = use_by_name.get(a.source_name)
                enriched_attrs.append({
                    "source_name": a.source_name,
                    "url": (u.source_url if u else "") or "",
                    "note": a.note,
                    "fair_value_delta": _round(a.fair_value_delta, 4),
                    "acquisition_method": u.acquisition_method if u else "free",
                    "cost_usd": _round(u.cost_usd, 5) if u else 0.0,
                })
            research_block = {
                "model": research.model,
                "confidence": _round(research.confidence, 3),
                "prior_fair_value": _round(research.prior_fair_value, 4),
                "fair_value": _round(research.fair_value, 4),
                "rationale": research.rationale,
                "llm_cost_usd": _round(research.token_cost_usd, 5),
                "source_attributions": enriched_attrs,
            }

        # ── data block ─────────────────────────────────────────────────────────
        data_block = {
            "total_cost_usd": _round(sum(u.cost_usd for u in data_uses), 5),
            "sources": [
                {
                    "source_name": u.source_name,
                    "url": u.source_url or "",
                    "source_type": u.source_type,
                    "acquisition_method": u.acquisition_method,
                    "cost_usd": _round(u.cost_usd, 5),
                    "datapoints": u.datapoints,
                }
                for u in data_uses
            ],
        }

        # ── risk block ─────────────────────────────────────────────────────────
        risk_block = None
        if risk is not None:
            checks = [
                {"name": name, "passed": bool(detail.get("pass", False))}
                for name, detail in risk.risk_checks.items()
            ]
            risk_block = {
                "market_price": _round(risk.market_price, 4),
                "fair_value": _round(risk.fair_value, 4),
                "edge": _round(risk.edge, 4),
                "kelly_inputs": risk.kelly_inputs,
                "size_usd": _round(risk.size_usd),
                "limit_price": _round(risk.limit_price, 4),
                "slippage_estimate": _round(risk.slippage_estimate, 4),
                "side": risk.side,
                "executed": risk.executed,
                "checks": checks,
            }

        llm_cost = research.token_cost_usd if research else 0.0
        data_cost = sum(u.cost_usd for u in data_uses)
        created_at = None
        if research is not None:
            created_at = _as_aware(research.created_at).isoformat()
        elif risk is not None:
            created_at = _as_aware(risk.created_at).isoformat()

        return {
            "decision_id": decision_id,
            "research": research_block,
            "data": data_block,
            "risk": risk_block,
            "trail_events": [
                {"agent": e.agent, "timestamp": _as_aware(e.timestamp).isoformat(), "text": e.text}
                for e in trail
            ],
            "cost_breakdown": {
                "reasoning_usd": _round(llm_cost, 5),
                "data_usd": _round(data_cost, 5),
            },
            "total_cost_usd": _round(llm_cost + data_cost, 5),
            "created_at": created_at,
        }


# ── FastAPI wiring ──────────────────────────────────────────────────────────

app = FastAPI(title="Honeybee Dashboard API", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_repo = build_repository()
_dash = Dashboard(_repo, _load_mandate())


@app.on_event("startup")
async def _startup() -> None:
    await _repo.init()


@app.get("/api/summary")
async def get_summary() -> dict:
    return await _dash.summary()


@app.get("/api/exposure")
async def get_exposure() -> list[dict]:
    return await _dash.exposure()


@app.get("/api/positions")
async def get_positions(status: str = Query("open", pattern="^(open|resolved)$")) -> list[dict]:
    return await _dash.positions(status)


@app.get("/api/decisions/{decision_id}")
async def get_decision(decision_id: str) -> dict:
    return await _dash.decision(decision_id)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}
