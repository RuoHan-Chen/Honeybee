"""Wallet abstraction — PaperWallet (default) and LiveWallet (--live flag).

PaperWallet: records intended fills, no chain interaction.
LiveWallet: loads private key from env, signs EIP-712 typed data, submits to CLOB.
            Stub implementation — full EIP-712 signing is P1 (§12 step 9).
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime

from ..contracts import Fill, TradeDecision, TradeSide

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
    """EIP-712 signing + CLOB submission — P1 stub.

    To enable: set POLYMARKET_PRIVATE_KEY in .env and pass --live flag.
    Full implementation (py_clob_client L1/L2 auth, token allowances) is §12 step 9.
    """

    is_live = True

    def __init__(self) -> None:
        self._private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
        if not self._private_key:
            raise EnvironmentError(
                "POLYMARKET_PRIVATE_KEY not set. "
                "Set it in .env or run without --live for paper trading."
            )
        log.warning("LiveWallet: EIP-712 signing is a stub — orders will NOT reach the chain.")

    async def submit(self, decision: TradeDecision, market_price: float) -> Fill | None:
        log.error(
            "LiveWallet.submit() called but full EIP-712 implementation is P1. "
            "Falling back to paper fill."
        )
        return await PaperWallet().submit(decision, market_price)


def build_wallet(live: bool = False) -> Wallet:
    if live:
        return LiveWallet()
    return PaperWallet()
