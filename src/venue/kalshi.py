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
import os
from datetime import datetime, timezone

import httpx

from ..contracts import Market
from .polymarket import _infer_vertical

log = logging.getLogger(__name__)

# Default to production for reads (richest market set). Set KALSHI_API_URL to the
# demo sandbox (https://external-api.demo.kalshi.co/trade-api/v2) to run the
# Kalshi demo flow end-to-end — reads + execution on the same env so tickers match.
PROD_API_URL = "https://api.elections.kalshi.com/trade-api/v2"
MAX_EVENT_PAGES = 12

# Niche series always pulled into discovery (override via KALSHI_SERIES), so
# long-tail markets like chess aren't buried behind the firehose depth/ordering.
DEFAULT_KALSHI_SERIES = "KXCHESSWORLDCHAMPION,KXCHESSGRANDTOUR,KXCHESSTOURNAMENT,KXCHESSOLYMPIAD"


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
        # demo (testnet) vs prod (mainnet) — drives the Kalshi flow's network.
        self.base = os.getenv("KALSHI_API_URL", PROD_API_URL).rstrip("/")

    async def list_markets(self, *, limit: int = 500) -> list[Market]:
        """Pull tradeable markets via the public Events API (nested markets).

        Two sources, deduped by ticker:
          1. Watchlist — configured niche series (chess by default) pulled
             directly by series_ticker, so they always surface regardless of depth.
          2. Firehose — the open-events feed, skipping MVE parlay noise and
             inactive (empty 0/1 book) markets, paged until `limit` is reached.
        """
        out: list[Market] = []
        seen: set[str] = set()

        # 1. Watchlist series — always included.
        watch = [s.strip() for s in os.getenv("KALSHI_SERIES", DEFAULT_KALSHI_SERIES).split(",") if s.strip()]
        for series in watch:
            if len(out) >= limit:
                break
            for m in await self._series_markets(series):
                if m.id not in seen and len(out) < limit:
                    seen.add(m.id)
                    out.append(m)

        # 2. Firehose.
        url = f"{self.base}/events"
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
                    if parsed is not None and parsed.id not in seen:
                        seen.add(parsed.id)
                        out.append(parsed)
                    if len(out) >= limit:
                        break
                if len(out) >= limit:
                    break

            cursor = data.get("cursor") or None
            if not cursor:
                break
        return out[:limit]

    async def _series_markets(self, series_ticker: str) -> list[Market]:
        """All open markets under one Kalshi series (the watchlist path).

        No activity gate — niche markets are often thin; discovery's own filter
        decides what's tradeable.
        """
        try:
            r = await self.http.get(
                f"{self.base}/events",
                params={"series_ticker": series_ticker, "status": "open", "with_nested_markets": "true"},
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.debug("kalshi series %s failed: %s", series_ticker, e)
            return []
        out: list[Market] = []
        for ev in data.get("events", []):
            for m in ev.get("markets", []):
                parsed = self._parse(m, ev)
                if parsed is not None:
                    out.append(parsed)
        return out

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
            r = await self.http.get(f"{self.base}/markets/{market_id}/orderbook")
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
