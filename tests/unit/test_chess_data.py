"""Chess Data connector: player-name extraction + FIDE Elo head-to-head."""
from __future__ import annotations

import pytest

from src.agents.data import _chess_candidate_names, _fetch_chess
from src.contracts import Market, Vertical


class _Resp:
    def __init__(self, data): self._data = data
    def raise_for_status(self): return None
    def json(self): return self._data


class _FideHttp:
    """Routes Lichess FIDE search by the q= param."""
    async def get(self, url, params=None):
        q = ((params or {}).get("q") or "").lower()
        db = {
            "carlsen": [{"id": 1, "name": "Carlsen, Magnus", "standard": 2841, "rapid": 2832,
                         "blitz": 2869, "title": "GM", "federation": "NOR"}],
            "nakamura": [{"id": 2, "name": "Nakamura, Hikaru", "standard": 2802, "rapid": 2700,
                          "blitz": 2800, "title": "GM", "federation": "USA"}],
        }
        for k, v in db.items():
            if k in q:
                return _Resp(v)
        return _Resp([])
    async def aclose(self): return None


def _mkt(q: str) -> Market:
    return Market(id="x", slug="x", url="", question=q, category="Chess", vertical=Vertical.other,
                  yes_price=0.5, no_price=0.5, spread=0.02, liquidity=100, volume_24h=500)


def test_candidate_names_extract_players_drop_event_words():
    names = _chess_candidate_names(
        "Will Magnus Carlsen beat Hikaru Nakamura in the World Chess Championship?")
    assert "Magnus Carlsen" in names
    assert "Hikaru Nakamura" in names
    assert all("Championship" not in n for n in names)   # event words filtered out


async def test_fetch_chess_elo_head_to_head():
    ds = await _fetch_chess(_mkt("Will Magnus Carlsen beat Hikaru Nakamura?"), _FideHttp())
    players = ds.datapoints["players"]
    assert {p["name"] for p in players} == {"Carlsen, Magnus", "Nakamura, Hikaru"}

    h2h = ds.datapoints["elo_head_to_head"]
    expected = 1.0 / (1.0 + 10 ** ((2802 - 2841) / 400.0))   # Carlsen's win prob
    assert h2h["Carlsen, Magnus"] == pytest.approx(round(expected, 4), abs=1e-3)
    assert ds.influenced_price is True


async def test_fetch_chess_single_player_no_h2h():
    ds = await _fetch_chess(_mkt("Will Magnus Carlsen win the title?"), _FideHttp())
    assert len(ds.datapoints["players"]) == 1
    assert "elo_head_to_head" not in ds.datapoints
