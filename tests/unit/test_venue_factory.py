"""Mode-driven venue selection: demo -> Kalshi, live -> Polymarket, VENUE pin."""
from __future__ import annotations

from src.venue.factory import build_venue


def test_demo_mode_selects_kalshi(monkeypatch):
    monkeypatch.delenv("VENUE", raising=False)
    assert build_venue(False).name == "kalshi"


def test_live_mode_selects_polymarket(monkeypatch):
    monkeypatch.delenv("VENUE", raising=False)
    assert build_venue(True).name == "polymarket"


def test_venue_pin_overrides_mode(monkeypatch):
    monkeypatch.setenv("VENUE", "polymarket")
    assert build_venue(False).name == "polymarket"   # pin beats demo default
    monkeypatch.setenv("VENUE", "kalshi")
    assert build_venue(True).name == "kalshi"          # pin beats live default
