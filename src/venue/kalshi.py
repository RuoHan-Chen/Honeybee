"""Kalshi venue adapter — public read paths (no auth required).

Mirrors the PolymarketAdapter surface (list_markets / get_best_prices) so the
Discovery agent can treat both venues uniformly. Order submission is out of
scope here (handled by the wallet/execution layer).

Notes from the live API:
  - Markets/orderbook reads are PUBLIC — no credentials needed for discovery.
  - Kalshi migrated to a fixed-point schema: prices arrive as dollar strings
    (`yes_bid_dollars`="0.0400", already 0..1), volume as `volume_24h_fp`,
    liquidity_dollars is dead (always 0) so we use open interest instead.
  - The flat /markets feed is ~99% auto-generated MVE parlay markets with empty
    books; /events surfaces the real tradeable markets, so we read from there.
  - The orderbook returns two *bid* arrays (yes/no); the ask side of an outcome
    is synthesised from the opposite outcome's bids (YES ask = 1 - NO bid).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from ..contracts import Market
from .polymarket import _infer_vertical

log = logging.getLogger(__name__)

API_URL = "https://api.elections.kalshi.com/trade-api/v2"   # public reads
MAX_EVENT_PAGES = 12


def _to_float(x: object) -> float | None:
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _norm_price(raw: object) -> float | None:
    """Normalise a price to 0..1. New API gives dollars; legacy gave cents (>1)."""
    v = _to_float(raw)
    if v is None:
        return None
    return v / 100.0 if v > 1.0 else v


class KalshiAdapter:
    name = "kalshi"

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=20.0)

    async def list_markets(self, *, limit: int = 500) -> list[Market]:
        """Pull tradeable markets via the public Events API (nested markets).

        Skips inactive markets (empty 0/1 books that clog the feed head) and
        pages until `limit` tradeable markets are collected.
        """
        url = f"{API_URL}/events"
        out: list[Market] = []
        cursor: str | None = None
        pages = 0

        while len(out) < limit and pages < MAX_EVENT_PAGES:
            params: dict[str, str] = {
                "limit": "200",
                "status": "open",
                "with_nested_markets": "true",
            }
            if cursor:
                params["cursor"] = cursor
            try:
                r = await self.http.get(url, params=params)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                log.warning("kalshi list_markets failed: %s", e)
                break
            pages += 1

            events = data.get("events", [])
            if not events:
                break
            for ev in events:
                if str(ev.get("event_ticker", "")).startswith("KXMVE"):
                    continue  # auto-generated parlay noise
                for m in ev.get("markets", []):
                    if not self._is_active(m):
                        continue
                    parsed = self._parse(m, ev)
                    if parsed is not None:
                        out.append(parsed)
                    if len(out) >= limit:
                        break
                if len(out) >= limit:
                    break

            cursor = data.get("cursor") or None
            if not cursor:
                break
        return out[:limit]

    @staticmethod
    def _is_active(m: dict) -> bool:
        return (_to_float(m.get("volume_24h_fp")) or 0.0) > 0 or \
            (_to_float(m.get("volume_24h")) or 0.0) > 0

    def _parse(self, m: dict, event: dict) -> Market | None:
        try:
            yes_bid = _norm_price(m.get("yes_bid_dollars") or m.get("yes_bid"))
            yes_ask = _norm_price(m.get("yes_ask_dollars") or m.get("yes_ask"))
            last = _norm_price(m.get("last_price_dollars") or m.get("last_price"))

            if yes_bid is not None and yes_ask is not None and yes_bid > 0 and yes_ask < 1 and yes_ask >= yes_bid:
                yes_price = (yes_bid + yes_ask) / 2.0
            elif last:
                yes_price = last
            elif yes_bid:
                yes_price = yes_bid
            else:
                yes_price = 0.5
            yes_price = min(0.99, max(0.01, yes_price))

            # Real market-level spread when both quotes exist (Polymarket can't
            # give this from its summary endpoint, so Kalshi candidates carry a
            # genuine spread signal into discovery).
            spread = 0.0
            if yes_bid is not None and yes_ask is not None and yes_ask >= yes_bid:
                spread = round(yes_ask - yes_bid, 4)

            close_iso = m.get("close_time")
            end_date = (
                datetime.fromisoformat(close_iso.replace("Z", "+00:00"))
                if close_iso else None
            )

            category = str(event.get("category") or "").strip()
            series = str(event.get("series_ticker") or "")
            tags = [t for t in [category.lower(), series.split("-")[0].lower()] if t]

            base_q = event.get("title") or m.get("title") or m.get("ticker", "")
            sub = m.get("yes_sub_title") or m.get("subtitle") or ""
            question = f"{base_q} — {sub}" if sub and sub.lower() not in base_q.lower() else base_q

            ticker = m.get("ticker", "")
            return Market(
                id=ticker,
                slug=ticker,
                url=f"https://kalshi.com/markets/{ticker}",
                question=question,
                category=category.lower(),
                vertical=_infer_vertical(tags, question),
                yes_price=round(yes_price, 4),
                no_price=round(1.0 - yes_price, 4),
                spread=spread,
                # liquidity_dollars is dead in Kalshi's schema; open interest
                # (contracts of live exposure) is the populated liquidity proxy.
                liquidity=_to_float(m.get("open_interest_fp")) or 0.0,
                volume_24h=_to_float(m.get("volume_24h_fp")) or _to_float(m.get("volume_24h")) or 0.0,
                end_date=end_date.astimezone(timezone.utc) if end_date else None,
                order_book_enabled=True,
            )
        except Exception as e:
            log.debug("skip kalshi market %s: %s", m.get("ticker"), e)
            return None

    async def get_best_prices(self, market_id: str) -> tuple[float, float] | None:
        """Best bid/ask for the YES outcome from the public orderbook.

        Kalshi returns two bid arrays; the YES ask side is synthesised from the
        NO bids (YES ask price = 1 - NO bid price).
        """
        try:
            r = await self.http.get(f"{API_URL}/markets/{market_id}/orderbook")
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.debug("kalshi orderbook failed for %s: %s", market_id, e)
            return None

        book = data.get("orderbook_fp") or data.get("orderbook") or {}
        yes_levels = book.get("yes_dollars") or book.get("yes") or []
        no_levels = book.get("no_dollars") or book.get("no") or []

        yes_bids = [p for p in (_norm_price(p) for p, _ in yes_levels) if p is not None]
        no_bids = [p for p in (_norm_price(p) for p, _ in no_levels) if p is not None]

        best_bid = max(yes_bids) if yes_bids else 0.0
        best_ask = (1.0 - max(no_bids)) if no_bids else 1.0
        return best_bid, best_ask

    async def close(self) -> None:
        await self.http.aclose()
