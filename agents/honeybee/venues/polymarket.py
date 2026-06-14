"""Polymarket adapter — reads via public Gamma + CLOB endpoints.

Read paths require no API key. Order submission is delegated to the TS
wallet service (which holds the Privy-signed EVM key); we never sign in
Python.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import CONFIG
from .base import (
    Fill, Market, Order, Orderbook, OrderbookLevel, VenueAdapter,
)

log = logging.getLogger(__name__)


class PolymarketAdapter(VenueAdapter):
    name = "polymarket"

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=20.0)

    async def list_markets(self, *, limit: int = 500) -> list[Market]:
        """Fetch active markets from the Gamma API (paginates as needed)."""
        url = f"{CONFIG.polymarket_gamma_url}/markets"
        out: list[Market] = []
        page_size = 100
        offset = 0
        while len(out) < limit:
            params = {
                "active": "true",
                "closed": "false",
                "limit": str(page_size),
                "offset": str(offset),
            }
            try:
                r = await self.http.get(url, params=params)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                log.warning("polymarket list_markets page %d failed: %s", offset, e)
                break

            batch = data if isinstance(data, list) else data.get("data", [])
            if not batch:
                break
            for m in batch:
                try:
                    out.append(self._parse_market(m))
                except Exception as e:
                    log.debug("skip polymarket market: %s", e)
            if len(batch) < page_size:
                break
            offset += page_size
        return out[:limit]

    def _parse_market(self, m: dict[str, Any]) -> Market:
        outcomes_raw = m.get("outcomes") or '["YES","NO"]'
        prices_raw = m.get("outcomePrices") or "[0.5,0.5]"

        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        prices_list = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

        prices = {
            outcomes[i]: float(prices_list[i])
            for i in range(min(len(outcomes), len(prices_list)))
        }

        close_iso = m.get("endDate") or m.get("endDateIso")
        close_time = None
        if close_iso:
            try:
                close_time = datetime.fromisoformat(close_iso.replace("Z", "+00:00"))
            except Exception:
                close_time = None

        tags = []
        for t in (m.get("tags") or []):
            label = t.get("label") if isinstance(t, dict) else str(t)
            if label:
                tags.append(label.lower())

        return Market(
            venue=self.name,
            market_id=str(m.get("id") or m.get("conditionId") or m.get("slug")),
            question=m.get("question") or m.get("title") or "",
            outcomes=[str(o) for o in outcomes],
            prices=prices,
            volume_24h=float(m.get("volume24hr") or m.get("volume24Hr") or 0.0),
            liquidity=float(m.get("liquidity") or m.get("liquidityNum") or 0.0),
            close_time=close_time.astimezone(timezone.utc) if close_time else None,
            resolution_source=m.get("resolutionSource"),
            tags=tags,
            url=f"https://polymarket.com/event/{m.get('slug')}" if m.get("slug") else None,
        )

    async def get_orderbook(self, market_id: str, outcome: str) -> Orderbook | None:
        """Fetch a CLOB orderbook for a specific token (outcome).

        Polymarket's CLOB is keyed by ERC1155 tokenId, not by our (market_id, outcome)
        pair directly. For MVP we look up the token via the Gamma market metadata.
        """
        try:
            gamma = await self.http.get(
                f"{CONFIG.polymarket_gamma_url}/markets/{market_id}"
            )
            gamma.raise_for_status()
            meta = gamma.json()
            token_ids_raw = meta.get("clobTokenIds") or "[]"
            token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
            outcomes_raw = meta.get("outcomes") or "[]"
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw

            if outcome not in outcomes:
                return None
            token_id = token_ids[outcomes.index(outcome)]
        except Exception as e:
            log.debug("polymarket token lookup failed for %s: %s", market_id, e)
            return None

        try:
            r = await self.http.get(
                f"{CONFIG.polymarket_clob_url}/book",
                params={"token_id": token_id},
            )
            r.raise_for_status()
            book = r.json()
        except Exception as e:
            log.debug("polymarket book fetch failed: %s", e)
            return None

        # Polymarket returns bids ascending and asks descending. Sort to
        # best-first (bids desc, asks asc) so best_bid/best_ask/spread and the
        # top-20 truncation reflect the real top of book — otherwise every
        # spread comes out ~0.98 from the worst levels.
        bids = sorted(
            (OrderbookLevel(float(b["price"]), float(b["size"])) for b in (book.get("bids") or [])),
            key=lambda lvl: lvl.price, reverse=True,
        )
        asks = sorted(
            (OrderbookLevel(float(a["price"]), float(a["size"])) for a in (book.get("asks") or [])),
            key=lambda lvl: lvl.price,
        )
        return Orderbook(
            market_id=market_id,
            outcome=outcome,
            bids=bids[:20],
            asks=asks[:20],
        )

    async def submit_order(self, order: Order) -> Fill | None:
        # All submission goes through the TS wallet service. Python is read-only.
        # The execution agent owns the HTTP call to the wallet service; we shouldn't
        # be called directly. Returning None signals "delegate".
        return None

    async def close(self) -> None:
        await self.http.aclose()
