"""Fractional Kelly sizing + circuit breakers.

All checks are recorded in the returned dict so they land in RiskDecisionRecord
and the frontend can show exactly what guarded (or blocked) a trade.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..contracts import Market, ResearchResult, TradeDecision, TradeSide


@dataclass
class SizingResult:
    decision: TradeDecision
    market_price: float
    risk_checks: dict[str, Any] = field(default_factory=dict)
    kelly_inputs: dict[str, Any] = field(default_factory=dict)
    slippage_estimate: float = 0.0


def compute_sizing(
    market: Market,
    research: ResearchResult,
    *,
    daily_loss_so_far: float,
    # mandate params (caller loads from mandate.yaml)
    bankroll_usd: float,
    kelly_fraction: float,
    max_exposure_per_market_usd: float,
    daily_loss_limit_usd: float,
    min_edge: float,
    min_confidence: float,
    max_liquidity_fraction: float,
) -> SizingResult:
    """Pure function — no I/O, no DB calls. Returns a SizingResult with all checks."""

    checks: dict[str, Any] = {}

    # ── 1. Circuit breaker: daily loss ───────────────────────────────────────
    checks["daily_loss_circuit_breaker"] = {
        "daily_loss_so_far": daily_loss_so_far,
        "limit": daily_loss_limit_usd,
        "pass": daily_loss_so_far > -daily_loss_limit_usd,
    }
    if not checks["daily_loss_circuit_breaker"]["pass"]:
        return _skip(
            market, research, checks, {},
            f"Daily loss limit hit (${daily_loss_so_far:.2f} vs limit ${daily_loss_limit_usd:.2f})",
        )

    # ── 2. Abstain flag from Research ────────────────────────────────────────
    checks["research_abstain"] = {"abstain": research.abstain, "pass": not research.abstain}
    if research.abstain:
        return _skip(market, research, checks, {}, "Research abstained — insufficient confidence")

    # ── 3. Confidence floor ───────────────────────────────────────────────────
    checks["confidence_floor"] = {
        "confidence": research.confidence,
        "floor": min_confidence,
        "pass": research.confidence >= min_confidence,
    }
    if not checks["confidence_floor"]["pass"]:
        return _skip(
            market, research, checks, {},
            f"Confidence {research.confidence:.2f} below floor {min_confidence:.2f}",
        )

    # ── 4. Pick side with maximum edge ────────────────────────────────────────
    yes_edge = research.fair_value - market.yes_price
    no_edge = (1 - research.fair_value) - market.no_price

    if yes_edge >= no_edge and yes_edge > 0:
        side = TradeSide.BUY_YES
        edge = yes_edge
        market_price = market.yes_price
    elif no_edge > 0:
        side = TradeSide.BUY_NO
        edge = no_edge
        market_price = market.no_price
    else:
        edge = max(yes_edge, no_edge)
        checks["edge_check"] = {"edge": edge, "min_edge": min_edge, "pass": False}
        return _skip(market, research, checks, {}, f"No positive edge (best={edge:.4f})")

    checks["edge_check"] = {
        "side": side.value,
        "edge": round(edge, 4),
        "min_edge": min_edge,
        "pass": edge >= min_edge,
    }
    if not checks["edge_check"]["pass"]:
        return _skip(
            market, research, checks, {},
            f"Edge {edge:.4f} below minimum {min_edge:.4f}",
        )

    # ── 5. Fractional Kelly ───────────────────────────────────────────────────
    b = (1.0 - market_price) / market_price if market_price > 0 else 1.0
    kelly_full = edge / b if b > 0 else 0.0
    kelly_fractional = kelly_fraction * kelly_full
    kelly_inputs = {
        "b": round(b, 4),
        "edge": round(edge, 4),
        "kelly_full": round(kelly_full, 4),
        "kelly_fraction": kelly_fraction,
        "kelly_fractional": round(kelly_fractional, 4),
    }
    stake_usd = bankroll_usd * kelly_fractional

    # ── 6. Per-market exposure cap ────────────────────────────────────────────
    pre_cap = stake_usd
    stake_usd = min(stake_usd, max_exposure_per_market_usd)
    checks["per_market_cap"] = {
        "pre_cap": round(pre_cap, 2),
        "cap": max_exposure_per_market_usd,
        "post_cap": round(stake_usd, 2),
        "pass": True,
    }

    # ── 7. Slippage / liquidity guard ─────────────────────────────────────────
    liq_cap = market.liquidity * max_liquidity_fraction
    slippage_estimate = 0.0
    if liq_cap > 0:
        slippage_estimate = min(stake_usd / max(market.liquidity, 1.0), 0.05)
        pre_liq = stake_usd
        stake_usd = min(stake_usd, liq_cap)
        checks["liquidity_slippage_guard"] = {
            "liquidity": market.liquidity,
            "max_fraction": max_liquidity_fraction,
            "liq_cap": round(liq_cap, 2),
            "pre_liq": round(pre_liq, 2),
            "post_liq": round(stake_usd, 2),
            "slippage_est": round(slippage_estimate, 4),
            "pass": True,
        }

    # ── 8. Minimum stake ──────────────────────────────────────────────────────
    checks["minimum_stake"] = {
        "stake_usd": round(stake_usd, 2),
        "minimum": 1.0,
        "pass": stake_usd >= 1.0,
    }
    if not checks["minimum_stake"]["pass"]:
        return _skip(
            market, research, checks, kelly_inputs,
            f"Stake ${stake_usd:.2f} below $1.00 minimum after all caps",
        )

    # ── Compute limit price and EV ────────────────────────────────────────────
    limit_price = round(market_price + 0.01, 4)   # cross 1 cent of spread
    expected_value = round(stake_usd * edge, 4)

    decision = TradeDecision(
        market_id=market.id,
        side=side,
        size_usd=round(stake_usd, 2),
        limit_price=limit_price,
        edge=round(edge, 4),
        expected_value=expected_value,
        reason=(
            f"Edge {edge*100:.1f}pts → Kelly {kelly_fractional*100:.2f}% "
            f"→ ${stake_usd:.2f}, within caps"
        ),
    )
    return SizingResult(
        decision=decision,
        market_price=market_price,
        risk_checks=checks,
        kelly_inputs=kelly_inputs,
        slippage_estimate=slippage_estimate,
    )


def _skip(
    market: Market,
    research: ResearchResult,
    checks: dict,
    kelly_inputs: dict,
    reason: str,
) -> SizingResult:
    return SizingResult(
        decision=TradeDecision(
            market_id=market.id,
            side=TradeSide.SKIP,
            reason=reason,
            edge=research.fair_value - market.yes_price,
        ),
        market_price=market.yes_price,
        risk_checks=checks,
        kelly_inputs=kelly_inputs,
    )
