"""Seed the SQLite store with a few complete decision trails so the dashboard
has open + resolved positions to render.

Real markets mostly SKIP (calibrated), so we synthesize executed trades here.
Uses ONLY the Repository write methods the agents themselves use — no schema changes.

Run:  python -m src.seed_dashboard
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .store.repository import (
    DataSourceUseRecord,
    FillRecord,
    MarketRecord,
    MarketSnapshot,
    OutcomeRecord,
    ResearchRecord,
    RiskDecisionRecord,
    SourceAttributionRecord,
    TrailEvent,
)
from .store.factory import build_repository
from .store.repository import Repository


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_one(
    repo: Repository,
    *,
    market_id: str,
    slug: str,
    question: str,
    category: str,
    vertical: str,
    yes_price: float,
    no_price: float,
    liquidity: float,
    volume_24h: float,
    days_to_expiry: int,
    side: str,
    entry_price: float,
    fair_value: float,
    confidence: float,
    rationale: str,
    model: str,
    llm_cost: float,
    size_usd: float,
    limit_price: float,
    kelly_inputs: dict,
    risk_checks: dict,
    slippage: float,
    data_sources: list[dict],
    attributions: list[dict],
    resolved: dict | None = None,
) -> str:
    decision_id = uuid4().hex
    ts0 = _now() - timedelta(hours=2)

    end_date = _now() + timedelta(days=days_to_expiry)

    # 1. Market
    await repo.upsert_market(MarketRecord(
        market_id=market_id, slug=slug, url=f"https://polymarket.com/event/{slug}",
        question=question, category=category, vertical=vertical,
        yes_price=yes_price, no_price=no_price, spread=round(1 - yes_price - no_price, 4),
        liquidity=liquidity, volume_24h=volume_24h, end_date=end_date,
        order_book_enabled=True, flagged_reason="seed", discovery_score=0.8,
    ))
    await repo.append_snapshot(MarketSnapshot(
        market_id=market_id, yes_price=yes_price, no_price=no_price,
        spread=round(1 - yes_price - no_price, 4), liquidity=liquidity, volume_24h=volume_24h,
    ))

    await repo.append_trail_event(TrailEvent(
        decision_id=decision_id, market_id=market_id, agent="orchestrator",
        timestamp=ts0, text=f"Evaluating: {question}",
        payload={"yes_price": yes_price, "no_price": no_price},
    ))

    # 2. Data sources
    total_data_cost = 0.0
    for i, ds in enumerate(data_sources):
        total_data_cost += ds["cost_usd"]
        await repo.append_data_source_use(DataSourceUseRecord(
            market_id=market_id, decision_id=decision_id,
            source_name=ds["source_name"], source_url=ds.get("url", ""),
            source_type=ds.get("source_type", "free"),
            datapoints=ds.get("datapoints", {}),
            acquisition_method=ds.get("acquisition_method", "free"),
            cost_usd=ds["cost_usd"], fetched_at=ts0 + timedelta(seconds=10 + i),
            influenced_price=ds.get("influenced_price", True),
            influenced_note=ds.get("note", ""),
        ))
        method = ds.get("acquisition_method", "free")
        cost_label = f" (${ds['cost_usd']:.4f})" if ds["cost_usd"] > 0 else " (free)"
        await repo.append_trail_event(TrailEvent(
            decision_id=decision_id, market_id=market_id, agent="data",
            timestamp=ts0 + timedelta(seconds=10 + i),
            text=f"Pulled {ds['source_name']} via {method}{cost_label}",
            payload={"datapoints": ds.get("datapoints", {})},
        ))

    # 3. Research + attributions
    await repo.append_trail_event(TrailEvent(
        decision_id=decision_id, market_id=market_id, agent="research",
        timestamp=ts0 + timedelta(seconds=30),
        text=f"Triage ({model}): worth_deep=True, quick_fair={fair_value:.3f}",
        payload={},
    ))
    running = yes_price
    for j, attr in enumerate(attributions):
        delta = attr["fair_value_delta"]
        await repo.append_source_attribution(SourceAttributionRecord(
            decision_id=decision_id, source_name=attr["source_name"],
            fair_value_delta=delta, note=attr.get("note", ""),
        ))
        await repo.append_trail_event(TrailEvent(
            decision_id=decision_id, market_id=market_id, agent="research",
            timestamp=ts0 + timedelta(seconds=35 + j),
            text=(f"{attr['source_name']} shifted fair value "
                  f"{running:.3f} → {running + delta:.3f} ({delta:+.3f}): {attr.get('note','')}"),
            payload=attr,
        ))
        running += delta

    await repo.upsert_research(ResearchRecord(
        decision_id=decision_id, market_id=market_id, vertical=vertical, model=model,
        prior_fair_value=yes_price, fair_value=fair_value, confidence=confidence,
        rationale=rationale, token_cost_usd=llm_cost, abstain=False,
        created_at=ts0 + timedelta(seconds=40),
    ))
    await repo.append_trail_event(TrailEvent(
        decision_id=decision_id, market_id=market_id, agent="research",
        timestamp=ts0 + timedelta(seconds=42),
        text=f"Deep analysis ({model}): fair_value={fair_value:.3f}, confidence={confidence:.2f}",
        payload={},
    ))

    # 4. Risk decision
    edge = fair_value - entry_price if side == "BUY_YES" else (1 - fair_value) - entry_price
    await repo.upsert_risk_decision(RiskDecisionRecord(
        decision_id=decision_id, market_id=market_id,
        market_price=entry_price, fair_value=fair_value, edge=edge,
        kelly_inputs=kelly_inputs, size_usd=size_usd, limit_price=limit_price,
        risk_checks=risk_checks, slippage_estimate=slippage, side=side,
        executed=True, reason=f"Edge {edge*100:.1f}pts → Kelly size ${size_usd:.2f}, within caps",
        created_at=ts0 + timedelta(seconds=50),
    ))
    await repo.append_trail_event(TrailEvent(
        decision_id=decision_id, market_id=market_id, agent="execution",
        timestamp=ts0 + timedelta(seconds=50),
        text=f"Edge {edge*100:.1f}pts → Kelly size ${size_usd:.2f}, limit={limit_price:.4f} — submitting {side}",
        payload=kelly_inputs,
    ))

    # 5. Fill
    await repo.append_fill(FillRecord(
        market_id=market_id, decision_id=decision_id, side=side,
        size_usd=size_usd, avg_price=entry_price,
        tx_ref=f"paper-{market_id}-{int(ts0.timestamp())}", paper=True,
        timestamp=ts0 + timedelta(seconds=52),
    ))
    await repo.append_trail_event(TrailEvent(
        decision_id=decision_id, market_id=market_id, agent="execution",
        timestamp=ts0 + timedelta(seconds=52),
        text=f"[paper] Filled {side} ${size_usd:.2f} @ {entry_price:.4f}",
        payload={},
    ))

    # 6. Optional resolution
    if resolved is not None:
        await repo.append_outcome(OutcomeRecord(
            market_id=market_id, decision_id=decision_id,
            resolved_value=resolved["resolved_value"],
            realized_pnl=resolved["realized_pnl"],
            was_calibrated=resolved.get("was_calibrated", True),
            recorded_at=_now() - timedelta(minutes=30),
        ))
        await repo.add_daily_pnl(
            (_now() - timedelta(minutes=30)).date().isoformat(), resolved["realized_pnl"]
        )
        await repo.append_trail_event(TrailEvent(
            decision_id=decision_id, market_id=market_id, agent="orchestrator",
            timestamp=_now() - timedelta(minutes=30),
            text=(f"Resolved {'YES' if resolved['resolved_value'] >= 0.5 else 'NO'} — "
                  f"realized P&L ${resolved['realized_pnl']:+.2f}"),
            payload=resolved,
        ))

    return decision_id


_PASS = {"pass": True}


async def seed() -> None:
    repo = build_repository()
    await repo.init()

    ids = []

    # ── Open position 1: macro / crypto, x402 paid data ──────────────────────
    ids.append(await _seed_one(
        repo,
        market_id="seed-btc-150k", slug="btc-150k-2026",
        question="Will Bitcoin close above $120,000 before Sept 2026?",
        category="crypto", vertical="macro",
        yes_price=0.38, no_price=0.62, liquidity=12000, volume_24h=2400,
        days_to_expiry=78, side="BUY_YES", entry_price=0.39, fair_value=0.52,
        confidence=0.68, model="claude-sonnet-4-6", llm_cost=0.0061,
        size_usd=22.0, limit_price=0.40,
        kelly_inputs={"b": 1.56, "edge": 0.13, "kelly_full": 0.083,
                      "kelly_fraction": 0.25, "kelly_fractional": 0.0208},
        risk_checks={"daily_loss_circuit_breaker": _PASS, "confidence_floor": _PASS,
                     "edge_check": _PASS, "per_market_cap": _PASS,
                     "liquidity_slippage_guard": _PASS, "minimum_stake": _PASS},
        slippage=0.004,
        data_sources=[
            {"source_name": "coingecko", "url": "https://api.coingecko.com/api/v3/simple/price",
             "source_type": "free", "acquisition_method": "free", "cost_usd": 0.0,
             "datapoints": {"price_usd": 64571, "change_24h_pct": 1.8}, "note": "BTC spot anchor"},
            {"source_name": "glassnode-onchain", "url": "https://glassnode.com",
             "source_type": "x402_paid", "acquisition_method": "x402_paid", "cost_usd": 0.004,
             "datapoints": {"mvrv_z": 1.2, "lth_supply_pct": 76.4}, "note": "on-chain accumulation signal"},
        ],
        attributions=[
            {"source_name": "coingecko", "fair_value_delta": 0.06,
             "note": "spot momentum supports upside vs market"},
            {"source_name": "glassnode-onchain", "fair_value_delta": 0.08,
             "note": "long-term holder accumulation historically precedes rallies"},
        ],
        rationale=("Market underprices the move: spot momentum plus strong long-term-holder "
                   "accumulation (MVRV-Z 1.2) historically precedes 6-month rallies. "
                   "Fair value 0.52 vs market 0.39 — 13pt edge."),
    ))

    # ── Open position 2: politics, free sources only ─────────────────────────
    ids.append(await _seed_one(
        repo,
        market_id="seed-senate-az", slug="senate-az-2026",
        question="Will the incumbent win the Arizona Senate race?",
        category="us-politics", vertical="politics",
        yes_price=0.55, no_price=0.45, liquidity=8000, volume_24h=1500,
        days_to_expiry=140, side="BUY_NO", entry_price=0.46, fair_value=0.61,
        confidence=0.63, model="claude-sonnet-4-6", llm_cost=0.0054,
        size_usd=15.5, limit_price=0.47,
        kelly_inputs={"b": 1.17, "edge": 0.15, "kelly_full": 0.128,
                      "kelly_fraction": 0.25, "kelly_fractional": 0.032},
        risk_checks={"daily_loss_circuit_breaker": _PASS, "confidence_floor": _PASS,
                     "edge_check": _PASS, "per_market_cap": _PASS,
                     "liquidity_slippage_guard": _PASS, "minimum_stake": _PASS},
        slippage=0.006,
        data_sources=[
            {"source_name": "perplexity-search", "url": "https://www.perplexity.ai",
             "source_type": "search_api", "acquisition_method": "search_api", "cost_usd": 0.002,
             "datapoints": {"recent_polls": "challenger +3.5 avg", "fundraising": "challenger leads"},
             "note": "recent polling aggregate"},
        ],
        attributions=[
            {"source_name": "perplexity-search", "fair_value_delta": 0.15,
             "note": "challenger polling lead not reflected in market price"},
        ],
        rationale=("Recent polling aggregate shows the challenger up ~3.5pts with a fundraising "
                   "edge, implying the incumbent is more likely to lose than the 55c YES suggests. "
                   "Buying NO at 0.46."),
    ))

    # ── Open position 3: sports, free ESPN ───────────────────────────────────
    ids.append(await _seed_one(
        repo,
        market_id="seed-nba-finals", slug="nba-finals-team-x",
        question="Will the Celtics reach the 2026 NBA Finals?",
        category="nba", vertical="sports",
        yes_price=0.30, no_price=0.70, liquidity=5500, volume_24h=900,
        days_to_expiry=45, side="BUY_YES", entry_price=0.31, fair_value=0.41,
        confidence=0.60, model="claude-sonnet-4-6", llm_cost=0.0049,
        size_usd=9.0, limit_price=0.32,
        kelly_inputs={"b": 2.23, "edge": 0.10, "kelly_full": 0.045,
                      "kelly_fraction": 0.25, "kelly_fractional": 0.011},
        risk_checks={"daily_loss_circuit_breaker": _PASS, "confidence_floor": _PASS,
                     "edge_check": _PASS, "per_market_cap": _PASS,
                     "liquidity_slippage_guard": _PASS, "minimum_stake": _PASS},
        slippage=0.005,
        data_sources=[
            {"source_name": "espn_nba_scoreboard",
             "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
             "source_type": "free", "acquisition_method": "free", "cost_usd": 0.0,
             "datapoints": {"net_rating_rank": 2, "recent_form": "8-2 L10"}, "note": "team form"},
        ],
        attributions=[
            {"source_name": "espn_nba_scoreboard", "fair_value_delta": 0.10,
             "note": "2nd-best net rating and strong recent form underpriced"},
        ],
        rationale=("Team holds the 2nd-best net rating and an 8-2 last-10 stretch; the market's "
                   "30c implies a longer path than the underlying form suggests. Fair 0.41."),
    ))

    # ── Resolved position: macro, won ────────────────────────────────────────
    ids.append(await _seed_one(
        repo,
        market_id="seed-fed-cut", slug="fed-cut-2026",
        question="Will the Fed cut rates at the July 2026 meeting?",
        category="economics", vertical="macro",
        yes_price=0.60, no_price=0.40, liquidity=15000, volume_24h=3200,
        days_to_expiry=-5, side="BUY_YES", entry_price=0.62, fair_value=0.78,
        confidence=0.72, model="claude-sonnet-4-6", llm_cost=0.0066,
        size_usd=20.0, limit_price=0.63,
        kelly_inputs={"b": 0.61, "edge": 0.16, "kelly_full": 0.262,
                      "kelly_fraction": 0.25, "kelly_fractional": 0.065},
        risk_checks={"daily_loss_circuit_breaker": _PASS, "confidence_floor": _PASS,
                     "edge_check": _PASS, "per_market_cap": _PASS,
                     "liquidity_slippage_guard": _PASS, "minimum_stake": _PASS},
        slippage=0.003,
        data_sources=[
            {"source_name": "perplexity-search", "url": "https://www.perplexity.ai",
             "source_type": "search_api", "acquisition_method": "search_api", "cost_usd": 0.002,
             "datapoints": {"cpi_trend": "cooling", "fed_funds_futures": "82% cut priced"},
             "note": "rate futures + CPI"},
        ],
        attributions=[
            {"source_name": "perplexity-search", "fair_value_delta": 0.16,
             "note": "fed funds futures price 82% odds vs market 62c"},
        ],
        rationale=("Fed funds futures imply ~82% odds of a cut and CPI is cooling, well above the "
                   "62c market. Bought YES."),
        resolved={"resolved_value": 1.0, "realized_pnl": 12.26, "was_calibrated": True},
    ))

    print(f"Seeded {len(ids)} decision trails:")
    for i in ids:
        print(f"  decision_id = {i}")


if __name__ == "__main__":
    asyncio.run(seed())
