"""Venue factory — selects the prediction-market venue by trading mode.

Mirrors build_repository() / build_wallet(): one switch, so the rest of the code
depends only on the adapter surface (list_markets / get_best_prices / close).

  demo / paper mode  -> Kalshi    (its sandbox supports safe fake-money fills)
  live mode          -> Polymarket (onchain settlement)

Pin explicitly with VENUE=kalshi|polymarket in .env to override the mode default.
"""
from __future__ import annotations

import os

from .kalshi import KalshiAdapter
from .polymarket import PolymarketAdapter

Venue = KalshiAdapter | PolymarketAdapter


def build_venue(live: bool = False) -> Venue:
    pin = os.getenv("VENUE", "").strip().lower()
    if pin == "kalshi":
        return KalshiAdapter()
    if pin == "polymarket":
        return PolymarketAdapter()
    return PolymarketAdapter() if live else KalshiAdapter()
