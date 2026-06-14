"""Kalshi adapter — public read paths (no auth required).

Kalshi's market + orderbook endpoints are public, so discovery works with no
credentials. Order *submission* is delegated to the TS wallet service, which
holds the user's API key and does the RSA-PSS request signing the authed
`/portfolio/*` endpoints require — we never sign in Python.

Read base URL defaults to production (real long-tail markets to analyse). The
TS execution service points at the demo sandbox for safe fills.

NOTE: Kalshi migrated to a fixed-point schema — prices arrive as dollar strings
(`yes_bid_dollars` = "0.0400", already 0..1) and the orderbook lives under
`orderbook_fp.{yes_dollars,no_dollars}`. The old integer-cents fields
(`yes_bid`, `volume_24h`, `orderbook.yes`) are gone. We parse the new schema and
fall back to the legacy cents shape so the adapter survives either.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from ..config import CONFIG
from .base import Fill, Market, Order, Orderbook, OrderbookLevel, VenueAdapter

log = logging.getLogger(__name__)


def _to_float(x: object) -> float | None:
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _norm_price(raw: object) -> float | None:
    """Normalise a price to 0..1. New API gives dollars; legacy gives cents (>1)."""
    v = _to_float(raw)
    if v is None:
        return None
    return v / 100.0 if v > 1.0 else v


class KalshiAdapter(VenueAdapter):
    name = "kalshi"

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=20.0)

    # Safety cap on pages per scan. Each page is 200 events (~1.7k nested
    # markets); active markets fill `limit` within ~2 pages, so this is rarely hit.
    MAX_EVENT_PAGES = 12

    async def list_markets(self, *, limit: int = 500) -> list[Market]:
        """Pull tradeable markets via the public Events API (nested markets).

        We query `/events` rather than `/markets`: the flat market listing is
        flooded with auto-generated MVE (Multi-Variant Event) parlay markets that
        bury the real long-tail markets. Events carry no MVE noise.

        The feed head is clogged with zero-activity markets (empty 0/1 books), so
        we skip inactive markets and keep paging until `limit` *tradeable* markets
        are collected — otherwise the budget is spent on dead markets and the
        in-band yield collapses (and varies as the feed re-sorts).
        """
        url = f"{CONFIG.kalshi_api_url}/events"
        out: list[Market] = []
        cursor: str | None = None
        pages = 0

        while len(out) < limit and pages < self.MAX_EVENT_PAGES:
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
                # Skip MVE parlay collections — combinatorial noise, never our edge.
                if str(ev.get("event_ticker", "")).startswith("KXMVE"):
                    continue
                for m in ev.get("markets", []):
                    if not self._is_active(m):
                        continue
                    parsed = self._parse_market(m, event=ev)
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
        """Has recent trading activity — filters out the empty 0/1-book markets
        that dominate the feed head and never pass downstream volume filters."""
        return (_to_float(m.get("volume_24h_fp")) or 0.0) > 0 or \
            (_to_float(m.get("volume_24h")) or 0.0) > 0

    def _parse_market(self, m: dict, event: dict | None = None) -> Market | None:
        try:
            # New schema: *_dollars strings (0..1). Legacy: integer cents.
            yes_bid = _norm_price(m.get("yes_bid_dollars") or m.get("yes_bid"))
            yes_ask = _norm_price(m.get("yes_ask_dollars") or m.get("yes_ask"))
            last = _norm_price(m.get("last_price_dollars") or m.get("last_price"))

            # Prefer a true two-sided midpoint; ignore the degenerate 0/1 book
            # that Kalshi shows for untraded markets. Fall back to last, then bid.
            if yes_bid is not None and yes_ask is not None and yes_bid > 0 and yes_ask < 1 and yes_ask >= yes_bid:
                yes_price = (yes_bid + yes_ask) / 2.0
            elif last:
                yes_price = last
            elif yes_bid:
                yes_price = yes_bid
            else:
                yes_price = 0.5
            yes_price = min(0.99, max(0.01, yes_price))

            close_iso = m.get("close_time")
            close_dt = (
                datetime.fromisoformat(close_iso.replace("Z", "+00:00"))
                if close_iso else None
            )

            # Category + question come from the parent event; the nested market
            # carries only a per-outcome sub-title (e.g. a strike range).
            ev = event or {}
            base_q = ev.get("title") or m.get("title") or m.get("ticker", "")
            sub = m.get("yes_sub_title") or m.get("subtitle") or ""
            question = f"{base_q} — {sub}" if sub and sub.lower() not in base_q.lower() else base_q

            tags: list[str] = []
            cat = ev.get("category") or m.get("category")
            if cat:
                tags.append(str(cat).lower())
            series = ev.get("series_ticker") or ""
            if series:
                tags.append(series.split("-")[0].lower())
            elif m.get("event_ticker"):
                tags.append(str(m["event_ticker"]).split("-")[0].lower())

            volume_24h = _to_float(m.get("volume_24h_fp")) or _to_float(m.get("volume_24h")) or 0.0
            # `liquidity_dollars` is dead in the new schema (always "0.0000" even on
            # deep books), so use open interest (contracts of live exposure) as the
            # populated liquidity proxy. Discovery refines this with real book depth.
            liquidity = (
                _to_float(m.get("open_interest_fp"))
                or _to_float(m.get("liquidity_dollars"))
                or _to_float(m.get("liquidity"))
                or 0.0
            )

            return Market(
                venue=self.name,
                market_id=m.get("ticker", ""),
                question=question,
                outcomes=["YES", "NO"],
                prices={"YES": round(yes_price, 4), "NO": round(1.0 - yes_price, 4)},
                volume_24h=volume_24h,
                liquidity=liquidity,
                close_time=close_dt.astimezone(timezone.utc) if close_dt else None,
                resolution_source=m.get("rules_primary") or None,
                tags=tags,
                url=f"https://kalshi.com/markets/{m.get('ticker', '')}",
            )
        except Exception as e:
            log.debug("skip kalshi market %s: %s", m.get("ticker"), e)
            return None

    async def get_orderbook(self, market_id: str, outcome: str) -> Orderbook | None:
        """Fetch the public orderbook for a ticker.

        Kalshi returns two *bid* arrays — `yes_dollars` and `no_dollars` (new) or
        `yes`/`no` (legacy cents) — each `[[price, size]]`. A resting NO bid at
        price p is economically an ask to sell YES at (1 - p), so we synthesise
        the ask side of the requested outcome from the opposite outcome's bids.
        Without this, spread/best_ask are unusable downstream.
        """
        try:
            r = await self.http.get(f"{CONFIG.kalshi_api_url}/markets/{market_id}/orderbook")
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.debug("kalshi orderbook failed for %s: %s", market_id, e)
            return None

        book = data.get("orderbook_fp") or data.get("orderbook") or {}
        yes_levels = book.get("yes_dollars") or book.get("yes") or []
        no_levels = book.get("no_dollars") or book.get("no") or []
        same, opposite = (yes_levels, no_levels) if outcome.upper() == "YES" else (no_levels, yes_levels)

        bids: list[OrderbookLevel] = []
        for p, s in same:
            price = _norm_price(p)
            if price is not None:
                bids.append(OrderbookLevel(price, _to_float(s) or 0.0))

        asks: list[OrderbookLevel] = []
        for p, s in opposite:
            price = _norm_price(p)
            if price is not None:
                asks.append(OrderbookLevel(round(1.0 - price, 4), _to_float(s) or 0.0))

        bids.sort(key=lambda lvl: lvl.price, reverse=True)
        asks.sort(key=lambda lvl: lvl.price)

        return Orderbook(
            market_id=market_id,
            outcome=outcome,
            bids=bids[:20],
            asks=asks[:20],
        )

    async def submit_order(self, order: Order) -> Fill | None:
        # All submission goes through the TS wallet service (RSA-signed, demo env).
        # Python is read-only; returning None signals "delegate".
        return None

    async def close(self) -> None:
        await self.http.aclose()
