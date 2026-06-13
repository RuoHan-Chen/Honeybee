"""Execution Agent — routes orders to the TS wallet service.

In DRY_RUN mode we still call the TS service (which does paper fills against
live orderbook snapshots) so the data path matches production.
If the wallet service is unreachable, we degrade gracefully to a Python-side
paper fill so the demo never blocks.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

import httpx

from ..config import CONFIG
from ..ledger import Ledger
from ..venues.base import Fill, Order

log = logging.getLogger(__name__)


class ExecutionAgent:
    def __init__(self, ledger: Ledger, http: httpx.AsyncClient | None = None) -> None:
        self.ledger = ledger
        self.http = http or httpx.AsyncClient(timeout=10.0)

    async def submit(self, order: Order, *, mid_price: float | None = None) -> Fill | None:
        # Idempotency check — never double-submit on crash recovery.
        if order.idempotency_key and await self.ledger.already_submitted(order.idempotency_key):
            log.info("execution: dedup, already submitted %s", order.idempotency_key)
            return None

        payload = {"order": asdict(order), "mid_price": mid_price}

        fill: Fill | None = None
        try:
            r = await self.http.post(f"{CONFIG.wallet_service_url}/submit", json=payload)
            r.raise_for_status()
            data = r.json()
            if data.get("fill"):
                f = data["fill"]
                fill = Fill(
                    venue=f["venue"], market_id=f["market_id"], outcome=f["outcome"],
                    side=f["side"], avg_price=float(f["avg_price"]),
                    filled_usd=float(f["filled_usd"]), fee_usd=float(f.get("fee_usd", 0)),
                    paper=bool(f.get("paper", True)),
                )
        except Exception as e:
            log.warning("execution: wallet service unreachable (%s) — falling back to local paper fill", e)
            fill = self._local_paper_fill(order, mid_price)

        if fill is not None:
            await self.ledger.mark_submitted(order.idempotency_key, asdict(order))
            await self.ledger.record("fill", asdict(fill), market_id=order.market_id)
        return fill

    def _local_paper_fill(self, order: Order, mid_price: float | None) -> Fill:
        # Pessimistic: assume we cross half the spread.
        px = mid_price if mid_price is not None else order.limit_price
        avg = min(order.limit_price, px + 0.005) if order.side == "BUY" else max(order.limit_price, px - 0.005)
        return Fill(
            venue=order.venue, market_id=order.market_id, outcome=order.outcome,
            side=order.side, avg_price=round(avg, 4),
            filled_usd=order.size_usd, fee_usd=0.0, paper=True,
        )
