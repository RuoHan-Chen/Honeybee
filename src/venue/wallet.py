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
            client.set_api_creds(client.create_or_derive_api_creds())
            log.info("LiveWallet ready (funder=%s sig_type=%d)", funder, self._sig_type)
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


def build_wallet(live: bool = False) -> Wallet:
    if live:
        return LiveWallet()
    return PaperWallet()
