"""Polymarket venue adapter — Gamma discovery + CLOB read-only.

All order submission goes through wallet.py (PaperWallet or LiveWallet).
Read endpoints are public; no auth required.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx

from ..contracts import Market, Vertical

log = logging.getLogger(__name__)

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"

_TAG_TO_VERTICAL: dict[str, Vertical] = {
    "sports": Vertical.sports,
    "nba": Vertical.sports,
    "nfl": Vertical.sports,
    "soccer": Vertical.sports,
    "mma": Vertical.sports,
    "politics": Vertical.politics,
    "election": Vertical.politics,
    "crypto": Vertical.macro,
    "economics": Vertical.macro,
    "weather": Vertical.weather,
}


def _infer_vertical(tags: list[str], question: str) -> Vertical:
    combined = " ".join(tags + [question.lower()])
    for keyword, vertical in _TAG_TO_VERTICAL.items():
        if keyword in combined:
            return vertical
    return Vertical.other


class PolymarketAdapter:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=20.0)

    async def list_markets(self, *, limit: int = 500) -> list[Market]:
        out: list[Market] = []
        page_size = 100
        offset = 0
        while len(out) < limit:
            params = {
                "active": "true",
                "closed": "false",
                "order_book_enabled": "true",
                "limit": str(page_size),
                "offset": str(offset),
            }
            try:
                r = await self.http.get(f"{GAMMA_URL}/markets", params=params)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                log.warning("polymarket list_markets page %d failed: %s", offset, e)
                break

            batch = data if isinstance(data, list) else data.get("data", [])
            if not batch:
                break
            for raw in batch:
                try:
                    m = self._parse(raw)
                    if m:
                        out.append(m)
                except Exception as e:
                    log.debug("skip market parse: %s", e)
            if len(batch) < page_size:
                break
            offset += page_size
        return out[:limit]

    def _parse(self, m: dict) -> Market | None:
        outcomes_raw = m.get("outcomes") or '["YES","NO"]'
        prices_raw = m.get("outcomePrices") or "[0.5,0.5]"
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

        if len(outcomes) < 2 or len(prices) < 2:
            return None

        yes_price = float(prices[0])
        no_price = float(prices[1])
        spread = max(0.0, 1.0 - yes_price - no_price)

        close_iso = m.get("endDate") or m.get("endDateIso")
        end_date: datetime | None = None
        if close_iso:
            try:
                end_date = datetime.fromisoformat(close_iso.replace("Z", "+00:00"))
            except Exception:
                pass

        tags = []
        for t in (m.get("tags") or []):
            label = t.get("label") if isinstance(t, dict) else str(t)
            if label:
                tags.append(label.lower())

        slug = m.get("slug") or ""
        market_id = str(m.get("id") or m.get("conditionId") or slug)
        if not market_id:
            return None

        return Market(
            id=market_id,
            slug=slug,
            url=f"https://polymarket.com/event/{slug}" if slug else "",
            question=m.get("question") or m.get("title") or "",
            category=tags[0] if tags else "",
            vertical=_infer_vertical(tags, m.get("question") or ""),
            yes_price=yes_price,
            no_price=no_price,
            spread=spread,
            liquidity=float(m.get("liquidity") or m.get("liquidityNum") or 0.0),
            volume_24h=float(m.get("volume24hr") or m.get("volume24Hr") or 0.0),
            end_date=end_date,
            order_book_enabled=bool(m.get("enableOrderBook", True)),
        )

    async def get_best_prices(self, market_id: str) -> tuple[float, float] | None:
        """Fetch live best-bid/ask from CLOB for YES token.
        Returns (best_bid, best_ask) or None on failure.
        """
        try:
            gamma = await self.http.get(f"{GAMMA_URL}/markets/{market_id}")
            gamma.raise_for_status()
            meta = gamma.json()
            token_ids_raw = meta.get("clobTokenIds") or "[]"
            token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
            if not token_ids:
                return None
            token_id = token_ids[0]   # YES token

            r = await self.http.get(f"{CLOB_URL}/book", params={"token_id": token_id})
            r.raise_for_status()
            book = r.json()
            # Polymarket returns bids ascending and asks descending, so bids[0]
            # / asks[0] are the WORST levels. Take max bid / min ask for the true
            # top of book (otherwise the spread reads ~0.98 on every market).
            bids = book.get("bids") or []
            asks = book.get("asks") or []
            best_bid = max((float(b["price"]) for b in bids), default=0.0)
            best_ask = min((float(a["price"]) for a in asks), default=1.0)
            return best_bid, best_ask
        except Exception as e:
            log.debug("clob book fetch failed for %s: %s", market_id, e)
            return None

    async def close(self) -> None:
        await self.http.aclose()
