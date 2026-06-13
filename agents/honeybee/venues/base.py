"""VenueAdapter abstraction + canonical trading types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


Side = Literal["BUY", "SELL"]
Venue = Literal["polymarket", "kalshi", "gemini"]


@dataclass
class Market:
    venue: str
    market_id: str
    question: str
    outcomes: list[str]
    prices: dict[str, float]            # outcome -> mid price (0..1)
    volume_24h: float
    liquidity: float
    close_time: datetime | None
    resolution_source: str | None = None
    tags: list[str] = field(default_factory=list)
    url: str | None = None

    @property
    def spread(self) -> float:
        """Best-effort spread proxy when we don't have a live book.

        For binary markets whose outcome prices already sum to ~1 (Polymarket
        summary endpoint), this returns 0 and callers should fall back to the
        live orderbook via `get_orderbook` for a real spread.
        """
        if len(self.prices) < 2:
            return 0.0
        vals = sorted(self.prices.values())
        return max(0.0, 1.0 - (vals[0] + vals[-1]))

    @property
    def uncertainty(self) -> float:
        """How close to 50/50 the market is — 1.0 means dead-flat, 0.0 means decided.

        For long-tail discovery, *flat* binary markets on clearly-skewed questions
        are themselves the opportunity (no algorithmic MM has priced them in).
        """
        if not self.prices:
            return 0.0
        # For binary: 1 - 2*|p - 0.5|. Generalises to n outcomes via entropy ratio.
        p = next(iter(self.prices.values()))
        return max(0.0, 1.0 - 2 * abs(p - 0.5))


@dataclass
class OrderbookLevel:
    price: float
    size: float


@dataclass
class Orderbook:
    market_id: str
    outcome: str
    bids: list[OrderbookLevel]
    asks: list[OrderbookLevel]

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> float:
        if self.best_bid is None or self.best_ask is None:
            return 0.0
        return max(0.0, self.best_ask - self.best_bid)


@dataclass
class Order:
    venue: str
    market_id: str
    outcome: str
    side: Side
    limit_price: float
    size_usd: float
    max_slippage_bps: int = 200
    dry_run: bool = True
    idempotency_key: str = ""


@dataclass
class Fill:
    venue: str
    market_id: str
    outcome: str
    side: Side
    avg_price: float
    filled_usd: float
    fee_usd: float = 0.0
    paper: bool = True


@dataclass
class Resolution:
    market_id: str
    resolved_outcome: str | None       # None if cancelled / void
    resolved_at: datetime


class VenueAdapter(ABC):
    name: str

    @abstractmethod
    async def list_markets(self, *, limit: int = 500) -> list[Market]: ...

    @abstractmethod
    async def get_orderbook(self, market_id: str, outcome: str) -> Orderbook | None: ...

    @abstractmethod
    async def submit_order(self, order: Order) -> Fill | None: ...

    async def get_resolution(self, market_id: str) -> Resolution | None:
        return None
