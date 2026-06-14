"""Wallet abstraction — PaperWallet (default) and LiveWallet (--live flag).

PaperWallet: records intended fills locally, no chain interaction.
LiveWallet:  real Polymarket CLOB execution via py-clob-client (mainnet).
"""
from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime

from ..contracts import Fill, TradeDecision, TradeSide
from .polymarket import resolve_clob_tokens

log = logging.getLogger(__name__)


class Wallet(ABC):
    @abstractmethod
    async def submit(self, decision: TradeDecision, market_price: float) -> Fill | None:
        """Submit a trade decision. Returns a Fill on success, None on skip/failure."""
        ...

    @property
    @abstractmethod
    def is_live(self) -> bool: ...


class PaperWallet(Wallet):
    """Records fills locally with no real capital movement."""

    is_live = False

    async def submit(self, decision: TradeDecision, market_price: float) -> Fill | None:
        if decision.side == TradeSide.SKIP:
            return None
        # Pessimistic fill: assume we cross ~half the spread (0.5ct slippage).
        slippage = 0.005
        if decision.side == TradeSide.BUY_YES:
            avg_price = min(decision.limit_price, market_price + slippage)
        else:
            avg_price = max(decision.limit_price, market_price - slippage)

        log.info(
            "[paper] %s market=%s size=$%.2f avg_price=%.4f",
            decision.side.value, decision.market_id, decision.size_usd, avg_price,
        )
        return Fill(
            market_id=decision.market_id,
            side=decision.side,
            size_usd=decision.size_usd,
            avg_price=round(avg_price, 4),
            tx_ref=f"paper-{decision.market_id[:8]}-{int(datetime.utcnow().timestamp())}",
            timestamp=datetime.utcnow(),
            paper=True,
        )


class LiveWallet(Wallet):
    """Live Polymarket CLOB execution via py-clob-client (Polygon mainnet).

    One-time prerequisites the operator must satisfy (cannot be done from here):
      - POLYMARKET_PRIVATE_KEY funded with USDC.e on Polygon (chain 137)
      - ERC-20/1155 allowances approving the Polymarket exchange contracts to
        move your USDC + conditional tokens. EOA wallets only — Magic/proxy
        wallets handle allowances automatically.
    Optional env:
      - POLYMARKET_SIGNATURE_TYPE  0 = EOA (default), 1 = Magic, 2 = browser proxy
      - POLYMARKET_FUNDER          defaults to signer address; set to the proxy
                                   address for signature_type 1/2
      - POLYMARKET_CLOB_URL        default https://clob.polymarket.com

    Polymarket has no testnet — this is mainnet-only, so a real fill cannot be
    dry-run without real funds. Use the Kalshi demo venue for safe execution tests.
    """

    is_live = True

    def __init__(self) -> None:
        pk = os.getenv("POLYMARKET_PRIVATE_KEY", "").strip()
        if not pk:
            raise EnvironmentError(
                "POLYMARKET_PRIVATE_KEY not set. "
                "Set it in .env or run without --live for paper trading."
            )
        self._pk = pk if pk.startswith("0x") else f"0x{pk}"
        self._sig_type = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0"))
        self._funder = os.getenv("POLYMARKET_FUNDER", "").strip() or None
        self._host = os.getenv("POLYMARKET_CLOB_URL", "https://clob.polymarket.com")
        # Optional pre-derived L2 API creds — skips the per-startup derive call.
        self._api_key = os.getenv("POLYMARKET_API_KEY", "").strip()
        self._api_secret = os.getenv("POLYMARKET_API_SECRET", "").strip()
        self._api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE", "").strip()
        self._client = None  # built lazily (pulls in signing/network deps)

    def _client_sync(self):
        """Build + auth the (synchronous) py-clob-client on first use."""
        if self._client is None:
            from eth_account import Account
            from py_clob_client.client import ClobClient

            funder = self._funder or Account.from_key(self._pk).address
            client = ClobClient(
                self._host, chain_id=137, key=self._pk,
                signature_type=self._sig_type, funder=funder,
            )
            # Prefer pre-derived L2 creds from env; otherwise derive from the key.
            if self._api_key and self._api_secret and self._api_passphrase:
                from py_clob_client.clob_types import ApiCreds
                client.set_api_creds(ApiCreds(self._api_key, self._api_secret, self._api_passphrase))
                creds_src = "env"
            else:
                client.set_api_creds(client.create_or_derive_api_creds())
                creds_src = "derived"
            log.info("LiveWallet ready (funder=%s sig_type=%d L2=%s)", funder, self._sig_type, creds_src)
            self._client = client
        return self._client

    async def submit(self, decision: TradeDecision, market_price: float) -> Fill | None:
        if decision.side == TradeSide.SKIP:
            return None
        tokens = await resolve_clob_tokens(decision.market_id)
        if not tokens:
            log.error("LiveWallet: could not resolve CLOB token for market %s", decision.market_id)
            return None
        yes_token, no_token = tokens
        token_id = yes_token if decision.side == TradeSide.BUY_YES else no_token
        try:
            # py-clob-client is synchronous — run it off the event loop.
            return await asyncio.to_thread(self._place, token_id, decision)
        except Exception as e:
            # Honest failure on a live order — never fake a paper fill.
            log.error("LiveWallet submit failed for %s (funds / allowance / liquidity?): %s",
                      decision.market_id, e)
            return None

    def _place(self, token_id: str, decision: TradeDecision) -> Fill | None:
        from py_clob_client.clob_types import MarketOrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY

        client = self._client_sync()
        # BUY_YES and BUY_NO are both *buys* of the respective outcome token.
        # Marketable FAK: fill what's available up to the slippage-capped price,
        # cancel the remainder — the right behaviour for thin long-tail books.
        args = MarketOrderArgs(
            token_id=token_id,
            amount=float(decision.size_usd),    # USDC to spend on the buy
            side=BUY,
            price=float(decision.limit_price),  # worst acceptable price (slippage cap)
            order_type=OrderType.FAK,
        )
        signed = client.create_market_order(args)
        resp = client.post_order(signed, OrderType.FAK) or {}

        order_id = resp.get("orderID") or resp.get("orderId") or resp.get("order_id") or ""
        status = resp.get("status") or resp.get("state") or ""
        if resp.get("success") is False or status in ("error", "failed") or not order_id:
            log.error("LiveWallet: order rejected for %s — resp=%s", decision.market_id, resp)
            return None

        log.info("[LIVE] %s market=%s $%.2f @<=%.4f order=%s status=%s",
                 decision.side.value, decision.market_id, decision.size_usd,
                 decision.limit_price, order_id, status)
        # Exact fill-amount reconciliation (trades endpoint) is a refinement;
        # record the submitted size + venue order id as the on-venue reference.
        return Fill(
            market_id=decision.market_id,
            side=decision.side,
            size_usd=float(decision.size_usd),
            avg_price=round(float(decision.limit_price), 4),
            tx_ref=str(order_id),
            timestamp=datetime.utcnow(),
            paper=False,
        )


class KalshiWallet(Wallet):
    """Live Kalshi execution via RSA-PSS-signed order submission.

    Defaults to the DEMO sandbox (KALSHI_API_URL) so fills cost no real money —
    the safe, provable execution path. Signing uses the system `openssl`
    (RSA-PSS-SHA256, salt = digest length) so there's no extra Python dependency,
    matching the scheme in execution/src/venues/kalshi.ts:
        signature = base64( RSA-PSS-SHA256( `${tsMs}${METHOD}${signingPath}` ) )

    Point KALSHI_API_URL at production only when you mean it (real money).
    """

    is_live = True
    _DEMO = "https://external-api.demo.kalshi.co/trade-api/v2"

    def __init__(self) -> None:
        self._base = os.getenv("KALSHI_API_URL", self._DEMO).rstrip("/")
        self._key_id = os.getenv("KALSHI_API_KEY_ID", "").strip()
        self._key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip()
        if not self._key_id or not self._key_path:
            raise EnvironmentError(
                "KalshiWallet needs KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH. "
                "Run without --live (paper) if you don't have Kalshi creds."
            )

    def _signed_headers(self, method: str, signing_path: str) -> dict[str, str]:
        import base64
        import subprocess
        import time

        ts = str(int(time.time() * 1000))  # Kalshi wants milliseconds
        message = f"{ts}{method}{signing_path}"
        proc = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", self._key_path,
             "-sigopt", "rsa_padding_mode:pss", "-sigopt", "rsa_pss_saltlen:digest", "-binary"],
            input=message.encode(), capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"openssl RSA-PSS sign failed: {proc.stderr.decode()[:200]}")
        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(proc.stdout).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }

    async def submit(self, decision: TradeDecision, market_price: float) -> Fill | None:
        if decision.side == TradeSide.SKIP:
            return None
        import uuid
        from urllib.parse import urlparse

        import httpx

        yes_no = "yes" if decision.side == TradeSide.BUY_YES else "no"
        # decision.limit_price is the slippage-capped worst acceptable price.
        px = max(0.01, min(0.99, round(decision.limit_price, 2)))
        count = max(1, int(decision.size_usd // px))
        price_field = "yes_price_dollars" if yes_no == "yes" else "no_price_dollars"
        body = {
            "ticker": decision.market_id, "action": "buy", "side": yes_no, "count": count,
            "type": "limit", price_field: f"{px:.2f}",
            "time_in_force": "immediate_or_cancel",   # marketable; cancels unfilled remainder
            "client_order_id": str(uuid.uuid4()),
        }
        # Signature path = full URL pathname incl. the /trade-api/v2 prefix, no query.
        signing_path = urlparse(f"{self._base}/portfolio/orders").path
        try:
            headers = self._signed_headers("POST", signing_path)
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(f"{self._base}/portfolio/orders", headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            # Honest failure — never fake a paper fill on a live order.
            log.error("KalshiWallet submit failed for %s (balance / liquidity / creds?): %s",
                      decision.market_id, e)
            return None

        order = data.get("order", {}) or {}
        filled = float(order.get("fill_count_fp") or 0)
        cost = float(order.get("taker_fill_cost_dollars") or 0)
        if filled <= 0:
            # IOC found no liquidity to cross — no position taken.
            log.warning("Kalshi IOC unfilled for %s (status=%s)", decision.market_id, order.get("status"))
            return None
        avg = round(cost / filled, 4)
        order_id = str(order.get("order_id", ""))
        log.info("[LIVE-kalshi] %s market=%s filled=%s @ %.4f cost=$%.2f order=%s",
                 decision.side.value, decision.market_id, filled, avg, cost, order_id)
        return Fill(
            market_id=decision.market_id,
            side=decision.side,
            size_usd=round(cost, 2),
            avg_price=avg,
            tx_ref=order_id,
            timestamp=datetime.utcnow(),
            paper=False,
        )


def build_wallet(live: bool = False) -> Wallet:
    """Paper by default. With live=True, pick the venue via VENUE env:
    VENUE=kalshi → KalshiWallet (demo sandbox = safe), else LiveWallet (Polymarket mainnet).
    """
    if not live:
        return PaperWallet()
    if os.getenv("VENUE", "").strip().lower() == "kalshi":
        return KalshiWallet()
    return LiveWallet()
