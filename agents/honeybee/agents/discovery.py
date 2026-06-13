"""Market Discovery Agent — finds long-tail mispriced opportunities."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from ..venues.base import Market, VenueAdapter

log = logging.getLogger(__name__)


@dataclass
class ScoredMarket:
    market: Market
    score: float
    reasons: list[str]


class DiscoveryAgent:
    """Scan all configured venues and rank candidate markets."""

    # Long-tail filter band (tunable via constructor).
    def __init__(
        self,
        venues: list[VenueAdapter],
        *,
        min_volume: float = 50.0,
        max_volume: float = 50_000.0,
        min_uncertainty: float = 0.6,        # flat-ish markets only (|p-0.5|<0.2)
        min_hours_to_close: float = 1.0,
        max_days_to_close: float = 365.0,
    ) -> None:
        self.venues = venues
        self.min_volume = min_volume
        self.max_volume = max_volume
        self.min_uncertainty = min_uncertainty
        self.min_hours_to_close = min_hours_to_close
        self.max_days_to_close = max_days_to_close

    async def scan(self, *, top_n: int = 20) -> list[ScoredMarket]:
        all_markets: list[Market] = []
        for v in self.venues:
            try:
                ms = await v.list_markets()
                log.info("discovery: %s returned %d markets", v.name, len(ms))
                all_markets.extend(ms)
            except Exception as e:
                log.warning("discovery: %s failed: %s", v.name, e)

        candidates: list[ScoredMarket] = []
        now = datetime.now(timezone.utc)

        for m in all_markets:
            reasons: list[str] = []

            if not (self.min_volume <= m.volume_24h <= self.max_volume):
                continue
            reasons.append(f"vol24h=${m.volume_24h:,.0f}")

            if m.uncertainty < self.min_uncertainty:
                continue
            reasons.append(f"uncertainty={m.uncertainty:.2f}")

            if m.close_time is None:
                continue
            hours_left = (m.close_time - now).total_seconds() / 3600
            if hours_left < self.min_hours_to_close:
                continue
            if hours_left / 24 > self.max_days_to_close:
                continue
            reasons.append(f"{hours_left:.0f}h to close")

            score = self._score(m, hours_left)
            candidates.append(ScoredMarket(market=m, score=score, reasons=reasons))

        candidates.sort(key=lambda x: x.score, reverse=True)
        log.info("discovery: %d / %d markets pass long-tail filter", len(candidates), len(all_markets))
        return candidates[:top_n]

    def _score(self, m: Market, hours_left: float) -> float:
        # Higher score for: flat (uncertain) + reasonable volume + not too far out.
        vol_score = math.log1p(m.volume_24h)
        time_decay = math.exp(-hours_left / (24 * 14))  # peak ~2 weeks out
        return m.uncertainty * vol_score * (0.3 + time_decay)
