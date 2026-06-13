"""Gemini Prediction Markets adapter — read stub.

Per PRD: https://developer.gemini.com/rest-api/prediction-markets/events
HMAC signing is handled in the TS wallet service.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from ..config import CONFIG
from .base import Fill, Market, Order, Orderbook, VenueAdapter

log = logging.getLogger(__name__)


class GeminiAdapter(VenueAdapter):
    name = "gemini"

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=20.0)

    @property
    def enabled(self) -> bool:
        return bool(CONFIG.gemini_api_key and CONFIG.gemini_api_secret)

    async def list_markets(self, *, limit: int = 500) -> list[Market]:
        if not self.enabled:
            return []
        try:
            r = await self.http.get(f"{CONFIG.gemini_api_url}/v1/predictions/events")
            r.raise_for_status()
            events = r.json()
        except Exception as e:
            log.warning("gemini list_markets failed: %s", e)
            return []

        out: list[Market] = []
        for ev in events if isinstance(events, list) else []:
            try:
                close_iso = ev.get("close_time") or ev.get("expiration")
                close_dt = datetime.fromisoformat(close_iso.replace("Z", "+00:00")) if close_iso else None
                outcomes = [o.get("name", str(i)) for i, o in enumerate(ev.get("outcomes", []))]
                prices = {
                    o.get("name", str(i)): float(o.get("price", 0.5))
                    for i, o in enumerate(ev.get("outcomes", []))
                }
                out.append(Market(
                    venue=self.name,
                    market_id=str(ev.get("event_id") or ev.get("id")),
                    question=ev.get("title", ""),
                    outcomes=outcomes or ["YES", "NO"],
                    prices=prices or {"YES": 0.5, "NO": 0.5},
                    volume_24h=float(ev.get("volume_24h", 0) or 0),
                    liquidity=float(ev.get("liquidity", 0) or 0),
                    close_time=close_dt.astimezone(timezone.utc) if close_dt else None,
                    tags=[ev.get("category", "").lower()] if ev.get("category") else [],
                ))
            except Exception:
                continue
        return out

    async def get_orderbook(self, market_id: str, outcome: str) -> Orderbook | None:
        return None  # implement once API shape confirmed with live key

    async def submit_order(self, order: Order) -> Fill | None:
        return None  # delegate to TS service
