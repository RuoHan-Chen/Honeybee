"""Polymarket get_best_prices must take top-of-book, not the worst levels.

Regression test for the bug where bids[0]/asks[0] (Polymarket returns bids
ascending, asks descending) gave ~0.98 spreads on every market.
"""
from __future__ import annotations

from src.venue.polymarket import PolymarketAdapter


class _Resp:
    def __init__(self, data): self._data = data
    def raise_for_status(self): return None
    def json(self): return self._data


class _Http:
    async def get(self, url, params=None):
        if "/book" in url:
            # Polymarket's real ordering: bids ascending, asks descending.
            return _Resp({
                "bids": [{"price": "0.01", "size": "1"}, {"price": "0.49", "size": "1"}],
                "asks": [{"price": "0.99", "size": "1"}, {"price": "0.50", "size": "1"}],
            })
        return _Resp({"clobTokenIds": '["tokYES","tokNO"]', "outcomes": '["Yes","No"]'})
    async def aclose(self): return None


async def test_best_prices_picks_top_of_book():
    bid, ask = await PolymarketAdapter(http=_Http()).get_best_prices("123")
    assert bid == 0.49   # max bid, NOT bids[0] == 0.01
    assert ask == 0.50   # min ask, NOT asks[0] == 0.99
