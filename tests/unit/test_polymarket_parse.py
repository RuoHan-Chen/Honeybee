"""Polymarket Gamma parsing + vertical inference (pure)."""
from __future__ import annotations

from src.contracts import Vertical
from src.venue.polymarket import PolymarketAdapter, _infer_vertical


def test_infer_vertical():
    assert _infer_vertical(["nba"], "lakers tonight") == Vertical.sports
    assert _infer_vertical([], "presidential election odds") == Vertical.politics
    assert _infer_vertical(["crypto"], "btc price") == Vertical.macro
    assert _infer_vertical(["weather"], "snow total") == Vertical.weather
    assert _infer_vertical([], "totally unrelated") == Vertical.other


def test_parse_gamma_market():
    raw = {
        "id": "123", "slug": "will-x", "question": "Will X happen?",
        "outcomes": '["Yes","No"]', "outcomePrices": '["0.40","0.60"]',
        "liquidity": "5000", "volume24hr": "1000",
        "endDate": "2030-01-01T00:00:00Z", "enableOrderBook": True,
        "tags": [{"label": "Politics"}],
    }
    m = PolymarketAdapter()._parse(raw)
    assert m is not None
    assert m.id == "123" and m.slug == "will-x"
    assert m.yes_price == 0.40 and m.no_price == 0.60
    assert m.liquidity == 5000.0 and m.volume_24h == 1000.0
    assert m.vertical == Vertical.politics
    assert m.order_book_enabled is True


def test_parse_rejects_malformed():
    # fewer than two outcomes -> None
    assert PolymarketAdapter()._parse({"id": "x", "outcomes": '["Yes"]', "outcomePrices": '["1.0"]'}) is None
