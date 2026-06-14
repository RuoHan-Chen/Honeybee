"""Kalshi adapter: price/schema parsing + orderbook ask-synthesis."""
from __future__ import annotations

import pytest

from src.venue.kalshi import KalshiAdapter, _norm_price


class _Resp:
    def __init__(self, data): self._data = data
    def raise_for_status(self): return None
    def json(self): return self._data


class _Http:
    def __init__(self, data): self._data = data
    async def get(self, url, params=None): return _Resp(self._data)
    async def aclose(self): return None


def test_norm_price_dollars_vs_cents():
    assert _norm_price("0.0400") == 0.04        # new dollar schema
    assert _norm_price("65") == 0.65            # legacy cents -> /100
    assert _norm_price(None) is None


def test_is_active_requires_volume():
    assert KalshiAdapter._is_active({"volume_24h_fp": "10"}) is True
    assert KalshiAdapter._is_active({"volume_24h_fp": "0"}) is False
    assert KalshiAdapter._is_active({}) is False


def test_parse_uses_bid_ask_mid_oi_and_spread():
    m = KalshiAdapter()._parse(
        {"ticker": "KXT-A", "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.44",
         "volume_24h_fp": "500", "open_interest_fp": "1000", "close_time": "2030-01-01T00:00:00Z"},
        {"title": "Will X happen?", "category": "Politics", "series_ticker": "KXT-2030"},
    )
    assert m is not None
    assert m.yes_price == 0.42 and m.no_price == 0.58       # midpoint of bid/ask
    assert m.spread == pytest.approx(0.04, abs=1e-6)        # real market spread
    assert m.liquidity == 1000.0                            # open-interest proxy
    assert m.volume_24h == 500.0


def test_parse_degenerate_book_defaults_to_half():
    m = KalshiAdapter()._parse(
        {"ticker": "X", "yes_bid_dollars": "0.00", "yes_ask_dollars": "1.00",
         "volume_24h_fp": "0", "close_time": "2030-01-01T00:00:00Z"},
        {"title": "Y"},
    )
    assert m.yes_price == 0.5


async def test_get_best_prices_synthesizes_ask_from_no_bids():
    book = {"orderbook_fp": {
        "yes_dollars": [["0.03", "100"], ["0.04", "200"]],
        "no_dollars":  [["0.45", "10"], ["0.40", "5"]],
    }}
    bid, ask = await KalshiAdapter(http=_Http(book)).get_best_prices("KXT-A")
    assert bid == 0.04                                # best (max) YES bid
    assert ask == pytest.approx(0.55, abs=1e-6)       # 1 - best NO bid (synthesized)
