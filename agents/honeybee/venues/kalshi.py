"""Kalshi adapter — stub. Active when KALSHI_EMAIL+KALSHI_PASSWORD are set."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from ..config import CONFIG
from .base import Fill, Market, Order, Orderbook, OrderbookLevel, VenueAdapter

log = logging.getLogger(__name__)


class KalshiAdapter(VenueAdapter):
    name = "kalshi"

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=20.0)
        self._token: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(CONFIG.kalshi_email and CONFIG.kalshi_password)

    async def _login(self) -> str | None:
        if self._token or not self.enabled:
            return self._token
        try:
            r = await self.http.post(
                f"{CONFIG.kalshi_api_url}/login",
                json={"email": CONFIG.kalshi_email, "password": CONFIG.kalshi_password},
            )
            r.raise_for_status()
            self._token = r.json().get("token")
        except Exception as e:
            log.warning("kalshi login failed: %s", e)
        return self._token

    async def list_markets(self, *, limit: int = 500) -> list[Market]:
        if not self.enabled:
            return []  # silently disabled until creds present
        # Public market listings don't strictly need auth, but bracket inside try.
        try:
            r = await self.http.get(
                f"{CONFIG.kalshi_api_url}/markets",
                params={"limit": min(limit, 1000), "status": "open"},
            )
            r.raise_for_status()
            ms = r.json().get("markets", [])
        except Exception as e:
            log.warning("kalshi list_markets failed: %s", e)
            return []

        out: list[Market] = []
        for m in ms:
            try:
                close_iso = m.get("close_time")
                close_dt = datetime.fromisoformat(close_iso.replace("Z", "+00:00")) if close_iso else None
                yes_price = float(m.get("yes_bid", 0)) / 100.0 if m.get("yes_bid") else 0.5
                no_price = 1.0 - yes_price
                out.append(Market(
                    venue=self.name,
                    market_id=m.get("ticker", ""),
                    question=m.get("title", ""),
                    outcomes=["YES", "NO"],
                    prices={"YES": yes_price, "NO": no_price},
                    volume_24h=float(m.get("volume_24h", 0)),
                    liquidity=float(m.get("liquidity", 0) or 0),
                    close_time=close_dt.astimezone(timezone.utc) if close_dt else None,
                    tags=[m.get("category", "").lower()] if m.get("category") else [],
                ))
            except Exception:
                continue
        return out

    async def get_orderbook(self, market_id: str, outcome: str) -> Orderbook | None:
        if not self.enabled:
            return None
        try:
            r = await self.http.get(f"{CONFIG.kalshi_api_url}/markets/{market_id}/orderbook")
            r.raise_for_status()
            book = r.json().get("orderbook", {})
            side = "yes" if outcome.upper() == "YES" else "no"
            bids_raw = book.get(side, [])  # [[price_cents, size], ...]
            return Orderbook(
                market_id=market_id,
                outcome=outcome,
                bids=[OrderbookLevel(p / 100.0, float(s)) for p, s in bids_raw[:20]],
                asks=[],
            )
        except Exception as e:
            log.debug("kalshi orderbook failed: %s", e)
            return None

    async def submit_order(self, order: Order) -> Fill | None:
        # Delegate to TS wallet service (token-auth path).
        return None
