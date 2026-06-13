"""Inter-agent x402 client.

Lets one agent purchase research from another. Wraps the x402 HTTP 402
protocol so the calling agent transparently settles a USDC-on-Arc payment
when prompted.

Real wiring: install `x402` (or `x402-python` once stable) and pass it the
agent's Privy wallet as the payer. For the MVP we degrade gracefully:
  - If the peer endpoint returns 200 immediately → use the response.
  - If 402 → if `X402_DRY_RUN=true` we synthesise a payment proof and retry
    once with a `X-PAYMENT-PROOF: mock-<hash>` header so peers can mock-accept.
  - If real Privy wallet present + `X402_DRY_RUN=false` → settle for real.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import CONFIG

log = logging.getLogger(__name__)


@dataclass
class PeerQuote:
    price_usd: float
    asset: str
    pay_to: str
    nonce: str


class PeerCallError(Exception):
    pass


class PeerCallClient:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=20.0)
        self._daily_spent = 0.0

    @property
    def daily_spent_usd(self) -> float:
        return self._daily_spent

    async def get_research(self, peer_url: str, market_id: str, *,
                           max_price_usd: float | None = None) -> dict[str, Any]:
        """Fetch research from a peer agent, settling x402 if required."""
        url = f"{peer_url.rstrip('/')}/research/{market_id}"
        r = await self.http.get(url)

        if r.status_code == 200:
            return r.json()

        if r.status_code != 402:
            raise PeerCallError(f"peer returned {r.status_code}: {r.text[:200]}")

        quote = _parse_402(r)
        cap = max_price_usd if max_price_usd is not None else float(
            os.getenv("X402_MAX_PAYMENT_USD", "0.10")
        )
        if quote.price_usd > cap:
            raise PeerCallError(
                f"peer quote ${quote.price_usd} exceeds cap ${cap}"
            )

        proof = await self._settle(quote)
        r2 = await self.http.get(url, headers={"X-PAYMENT-PROOF": proof})
        if r2.status_code != 200:
            raise PeerCallError(f"peer rejected payment proof: {r2.status_code} {r2.text[:200]}")
        self._daily_spent += quote.price_usd
        return r2.json()

    async def _settle(self, quote: PeerQuote) -> str:
        """Produce a payment proof header.

        In real mode this calls the TS wallet service to sign+broadcast a
        USDC transfer on Arc to `quote.pay_to`. In mock mode we return a
        deterministic stub proof so peer agents running in mock mode accept it.
        """
        dry = os.getenv("X402_DRY_RUN", "true").lower() in ("1", "true", "yes")
        if dry:
            h = hashlib.sha256(
                f"{quote.pay_to}:{quote.nonce}:{quote.price_usd}".encode()
            ).hexdigest()
            return f"mock-{h[:24]}"

        # Real path: ask TS wallet service to settle.
        try:
            r = await self.http.post(
                f"{CONFIG.wallet_service_url}/x402/settle",
                json={
                    "to": quote.pay_to,
                    "amount_usd": quote.price_usd,
                    "asset": quote.asset,
                    "nonce": quote.nonce,
                },
            )
            r.raise_for_status()
            return r.json()["proof"]
        except Exception as e:
            raise PeerCallError(f"x402 settle failed: {e}") from e


def _parse_402(resp: httpx.Response) -> PeerQuote:
    """Extract a PeerQuote from an x402 challenge response.

    Supports either a JSON body `{ price_usd, asset, pay_to, nonce }` or
    standard x402 headers (`X-PAYMENT-AMOUNT`, `X-PAYMENT-RECIPIENT`,
    `X-PAYMENT-NONCE`, `X-PAYMENT-ASSET`).
    """
    try:
        j = resp.json()
        return PeerQuote(
            price_usd=float(j["price_usd"]),
            asset=str(j.get("asset", "USDC")),
            pay_to=str(j["pay_to"]),
            nonce=str(j.get("nonce", "0")),
        )
    except Exception:
        return PeerQuote(
            price_usd=float(resp.headers.get("X-PAYMENT-AMOUNT", "0.01")),
            asset=resp.headers.get("X-PAYMENT-ASSET", "USDC"),
            pay_to=resp.headers.get("X-PAYMENT-RECIPIENT", "0x0"),
            nonce=resp.headers.get("X-PAYMENT-NONCE", "0"),
        )
