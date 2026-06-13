"""Risk Agent — fractional Kelly sizing + circuit breakers."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date

from ..config import CONFIG
from ..ledger import Ledger
from ..venues.base import Market, Order
from .research import ResearchSignal

log = logging.getLogger(__name__)


@dataclass
class SizingDecision:
    order: Order | None
    rejected_reason: str | None = None
    edge: float = 0.0
    kelly_fraction: float = 0.0


class RiskAgent:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    async def size(self, m: Market, signal: ResearchSignal) -> SizingDecision:
        # 0. Circuit breakers
        today = date.today().isoformat()
        realised = await self.ledger.get_daily_loss(today)
        if realised <= -CONFIG.daily_loss_limit_usd:
            return SizingDecision(None, rejected_reason=f"daily loss limit hit ({realised:.2f})")

        # 1. Confidence floor
        if signal.confidence < CONFIG.confidence_floor:
            return SizingDecision(None, rejected_reason=f"confidence {signal.confidence:.2f} < floor")

        # 2. Pick the outcome with the largest edge
        best_outcome = None
        best_edge = 0.0
        best_market_price = 0.0
        best_fair = 0.0
        for outcome, fair in signal.fair_prices.items():
            mkt_price = m.prices.get(outcome)
            if mkt_price is None or mkt_price <= 0 or mkt_price >= 1:
                continue
            edge = fair - mkt_price
            if edge > best_edge:
                best_edge = edge
                best_outcome = outcome
                best_market_price = mkt_price
                best_fair = fair

        if best_outcome is None or best_edge < 0.02:
            return SizingDecision(None, rejected_reason=f"insufficient edge ({best_edge:.3f})")

        # 3. Fractional Kelly
        b = (1 - best_market_price) / best_market_price       # decimal odds payoff
        kelly = best_edge / b
        sized_fraction = max(0.0, min(CONFIG.kelly_fraction * kelly, CONFIG.max_fraction_per_market))
        stake_usd = CONFIG.bankroll_usd * sized_fraction

        # 4. Hard exposure cap per market
        stake_usd = min(stake_usd, CONFIG.max_exposure_per_market_usd)

        # 5. Liquidity / slippage guard — no more than 5% of stated liquidity
        liq_cap = max(0.0, m.liquidity * 0.05)
        if liq_cap > 0 and stake_usd > liq_cap:
            stake_usd = liq_cap

        if stake_usd < 1.0:
            return SizingDecision(
                None,
                rejected_reason=f"stake ${stake_usd:.2f} below $1 minimum",
                edge=best_edge,
                kelly_fraction=kelly,
            )

        idem = _idempotency_key(m, best_outcome, best_fair)

        order = Order(
            venue=m.venue,
            market_id=m.market_id,
            outcome=best_outcome,
            side="BUY",
            limit_price=round(best_market_price + 0.01, 4),  # cross 1ct of spread
            size_usd=round(stake_usd, 2),
            max_slippage_bps=200,
            dry_run=CONFIG.dry_run,
            idempotency_key=idem,
        )
        return SizingDecision(order=order, edge=best_edge, kelly_fraction=kelly)


def _idempotency_key(m: Market, outcome: str, fair: float) -> str:
    raw = f"{m.venue}:{m.market_id}:{outcome}:{round(fair, 2)}:{date.today().isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
