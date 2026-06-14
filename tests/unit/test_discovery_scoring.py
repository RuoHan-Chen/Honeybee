"""Discovery score: flat (unpriced) + active + closing-soon ranks higher."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.discovery import _score
from src.contracts import Market, Vertical


def _mkt(yes: float, vol: float, hours_to_close: float = 120.0) -> tuple[Market, float]:
    m = Market(id="x", slug="x", url="", question="q", category="", vertical=Vertical.other,
               yes_price=yes, no_price=round(1 - yes, 4), spread=0.0, liquidity=1000.0,
               volume_24h=vol, end_date=datetime.now(timezone.utc) + timedelta(hours=hours_to_close),
               order_book_enabled=True)
    return m, hours_to_close


def test_flat_market_scores_above_decided():
    flat, h = _mkt(0.50, 1000.0)
    decided, _ = _mkt(0.95, 1000.0)
    assert _score(flat, h) > _score(decided, h)


def test_more_volume_scores_higher():
    hi, h = _mkt(0.50, 5000.0)
    lo, _ = _mkt(0.50, 100.0)
    assert _score(hi, h) > _score(lo, h)


def test_closing_sooner_scores_higher():
    soon, hs = _mkt(0.50, 1000.0, hours_to_close=24.0)
    far, hf = _mkt(0.50, 1000.0, hours_to_close=24 * 60.0)
    assert _score(soon, hs) > _score(far, hf)
