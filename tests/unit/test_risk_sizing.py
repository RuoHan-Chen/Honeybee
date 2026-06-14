"""Risk/Kelly sizing — the money logic. Pure function, no I/O."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.contracts import Market, ResearchResult, TradeSide
from src.risk.sizing import compute_sizing

PARAMS = dict(
    bankroll_usd=1000.0,
    kelly_fraction=0.25,
    max_exposure_per_market_usd=25.0,
    daily_loss_limit_usd=100.0,
    min_edge=0.05,
    min_confidence=0.55,
    max_liquidity_fraction=0.05,
)


def _market(yes=0.40, no=0.60, liq=10_000.0, vol=1_000.0) -> Market:
    return Market(
        id="m1", slug="m1", url="", question="q", category="",
        yes_price=yes, no_price=no, spread=0.0, liquidity=liq, volume_24h=vol,
        end_date=datetime.now(timezone.utc) + timedelta(days=5), order_book_enabled=True,
    )


def _research(fair=0.55, conf=0.80, abstain=False) -> ResearchResult:
    return ResearchResult(market_id="m1", prior_fair_value=0.5, fair_value=fair,
                          confidence=conf, rationale="r", abstain=abstain)


def test_positive_edge_buys_yes_within_cap():
    r = compute_sizing(_market(yes=0.40), _research(fair=0.55), daily_loss_so_far=0.0, **PARAMS)
    assert r.decision.side == TradeSide.BUY_YES
    assert r.decision.edge > 0
    assert 0 < r.decision.size_usd <= PARAMS["max_exposure_per_market_usd"]


def test_daily_loss_circuit_breaker_skips():
    r = compute_sizing(_market(), _research(), daily_loss_so_far=-150.0, **PARAMS)
    assert r.decision.side == TradeSide.SKIP
    assert r.risk_checks["daily_loss_circuit_breaker"]["pass"] is False


def test_low_confidence_skips():
    r = compute_sizing(_market(yes=0.40), _research(fair=0.55, conf=0.50), daily_loss_so_far=0.0, **PARAMS)
    assert r.decision.side == TradeSide.SKIP


def test_no_edge_skips():
    r = compute_sizing(_market(yes=0.55, no=0.45), _research(fair=0.55), daily_loss_so_far=0.0, **PARAMS)
    assert r.decision.side == TradeSide.SKIP


def test_abstain_skips():
    r = compute_sizing(_market(yes=0.40), _research(fair=0.55, abstain=True), daily_loss_so_far=0.0, **PARAMS)
    assert r.decision.side == TradeSide.SKIP


def test_per_market_cap_clamps_large_kelly():
    # A huge edge + deep liquidity would size large; the per-market cap must bind.
    r = compute_sizing(_market(yes=0.20, no=0.80, liq=10_000_000.0),
                       _research(fair=0.90, conf=0.95), daily_loss_so_far=0.0, **PARAMS)
    assert r.decision.side == TradeSide.BUY_YES
    assert r.decision.size_usd <= PARAMS["max_exposure_per_market_usd"]


def test_buys_no_when_no_side_has_the_edge():
    # fair 0.30 -> NO edge (0.70 - 0.45) beats the negative YES edge.
    r = compute_sizing(_market(yes=0.55, no=0.45), _research(fair=0.30, conf=0.80),
                       daily_loss_so_far=0.0, **PARAMS)
    assert r.decision.side == TradeSide.BUY_NO


def test_minimum_stake_skips_when_below_one_dollar():
    # Tiny bankroll -> Kelly stake < $1 -> SKIP on the minimum-stake guard.
    params = {**PARAMS, "bankroll_usd": 10.0}
    r = compute_sizing(_market(yes=0.49, no=0.51), _research(fair=0.55, conf=0.80),
                       daily_loss_so_far=0.0, **params)
    assert r.decision.side == TradeSide.SKIP
    assert r.risk_checks["minimum_stake"]["pass"] is False
