"""Market Discovery Agent — finds long-tail mispriced opportunities.

Ranking targets the *thesis*, not liquidity: flat (unpriced) markets with thin
books and low venue-relative volume score highest. Deep, efficient, high-volume
markets — the quant battleground — are pushed down even when their raw activity
is large. Scoring multiplies independent 0..~1.3 factors so no single signal
dominates, and the per-venue volume normalisation keeps low-volume venues
(e.g. Kalshi) from being buried under high dollar-volume venues (Polymarket).
"""
from __future__ import annotations

import asyncio
import bisect
import logging
import re
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from ..venues.base import Market, VenueAdapter

log = logging.getLogger(__name__)


@dataclass
class ScoredMarket:
    market: Market
    score: float
    reasons: list[str]
    spread: float = 0.0          # real best_ask - best_bid from the live book (0 if unknown)
    book_notional: float = 0.0   # Σ price×size of resting depth, in USD (0 if unknown)


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
        enrich_books: bool = True,           # pull live order books for candidates
        max_book_fetches: int = 60,          # cap concurrent book fetches per scan
        min_book_notional: float = 50.0,     # USD of resting depth to count as tradeable
        book_soft_cap: float = 5_000.0,      # thinness decays past this much resting depth
        book_concurrency: int = 8,
    ) -> None:
        self.venues = venues
        self.venues_by_name = {v.name: v for v in venues}
        self.min_volume = min_volume
        self.max_volume = max_volume
        self.min_uncertainty = min_uncertainty
        self.min_hours_to_close = min_hours_to_close
        self.max_days_to_close = max_days_to_close
        self.enrich_books = enrich_books
        self.max_book_fetches = max_book_fetches
        self.min_book_notional = min_book_notional
        self.book_soft_cap = book_soft_cap
        self.book_concurrency = book_concurrency

    async def scan(self, *, top_n: int = 20) -> list[ScoredMarket]:
        all_markets: list[Market] = []
        for v in self.venues:
            try:
                ms = await v.list_markets()
                log.info("discovery: %s returned %d markets", v.name, len(ms))
                all_markets.extend(ms)
            except Exception as e:
                log.warning("discovery: %s failed: %s", v.name, e)

        now = datetime.now(timezone.utc)
        candidates: list[ScoredMarket] = []

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

            candidates.append(ScoredMarket(market=m, score=0.0, reasons=reasons))

        log.info("discovery: %d / %d markets pass long-tail filter", len(candidates), len(all_markets))
        if not candidates:
            return []

        # Enrich with live order books so thinness/spread are real signals, not
        # guesses. Only ~tens of markets survive the filter, so we fetch all of
        # them (up to a cap) rather than a prelim top-K — avoids a chicken-and-egg
        # where the score depends on a book we didn't fetch.
        if self.enrich_books:
            await self._enrich_books(candidates[: self.max_book_fetches])

        # Per-venue volume percentile (0 = lowest volume in its venue → most long-tail).
        vol_by_venue: dict[str, list[float]] = defaultdict(list)
        for sm in candidates:
            vol_by_venue[sm.market.venue].append(sm.market.volume_24h)
        for arr in vol_by_venue.values():
            arr.sort()

        for sm in candidates:
            arr = vol_by_venue[sm.market.venue]
            pctile = bisect.bisect_left(arr, sm.market.volume_24h) / (len(arr) - 1) if len(arr) > 1 else 0.0
            sm.score = self._score(sm, hours_left=self._hours_left(sm.market, now), vol_pctile=pctile)

        candidates.sort(key=lambda x: x.score, reverse=True)
        # De-dupe by series (drop the trailing strike/threshold segment) so one
        # event's many contract variants — e.g. "vote % >= 25/50/…" on the same
        # election — don't crowd out variety. Keep the highest-scored per series.
        seen_series: set[str] = set()
        deduped: list[ScoredMarket] = []
        for sm in candidates:
            key = re.split(r"-\d", str(sm.market.market_id))[0]  # event-level (drop strike/sub-market)
            if key in seen_series:
                continue
            seen_series.add(key)
            deduped.append(sm)
        return deduped[:top_n]

    async def _enrich_books(self, scored: list[ScoredMarket]) -> None:
        sem = asyncio.Semaphore(self.book_concurrency)

        async def one(sm: ScoredMarket) -> None:
            adapter = self.venues_by_name.get(sm.market.venue)
            if adapter is None or not sm.market.outcomes:
                return
            async with sem:
                try:
                    ob = await adapter.get_orderbook(sm.market.market_id, sm.market.outcomes[0])
                except Exception as e:
                    log.debug("discovery: book fetch failed for %s: %s", sm.market.market_id, e)
                    return
            if ob is None:
                return
            sm.spread = ob.spread
            sm.book_notional = sum(lvl.price * lvl.size for lvl in ob.bids) + \
                sum(lvl.price * lvl.size for lvl in ob.asks)
            if sm.book_notional > 0:
                sm.reasons.append(f"book=${sm.book_notional:,.0f}/spread={sm.spread:.3f}")

        await asyncio.gather(*(one(sm) for sm in scored))

    @staticmethod
    def _hours_left(m: Market, now: datetime) -> float:
        return (m.close_time - now).total_seconds() / 3600 if m.close_time else 24 * 14

    def _score(self, sm: ScoredMarket, *, hours_left: float, vol_pctile: float) -> float:
        """Product of independent long-tail factors (each ~0..1.3).

        High score = flat + thin + low-relative-volume + moderately-wide-spread +
        not-too-far-out. Deep, efficient, high-volume markets are suppressed.
        """
        m = sm.market
        unc = m.uncertainty                                   # 0..1   flat = unpriced
        thin = self._thinness_factor(sm.book_notional)        # ~0.2..1
        spread = self._spread_factor(sm.spread)               # 0.8..1.3
        lowvol = 1.2 - 0.7 * vol_pctile                       # 1.2 (lowest vol) .. 0.5 (highest)
        time_decay = 0.3 + math.exp(-hours_left / (24 * 14))  # ~0.3..1.3, peak ~2wks out
        return unc * thin * spread * lowvol * time_decay

    def _thinness_factor(self, notional: float) -> float:
        # Reward thin (but tradeable) books; decay hard for deep/efficient books.
        if notional <= 0:
            return 0.6                                        # unknown book (e.g. no public book)
        if notional < self.min_book_notional:
            return 0.3                                        # too thin to actually trade
        return 1.0 / (1.0 + notional / self.book_soft_cap)

    @staticmethod
    def _spread_factor(spread: float) -> float:
        # Mild reward for a wider-than-efficient spread (unpriced), capped so a
        # near-dead book can't win on spread alone.
        return 0.8 + min(spread, 0.15) / 0.15 * 0.5
