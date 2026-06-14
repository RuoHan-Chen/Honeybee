"""Data Agent — separate process, polls task queue for 'fetch_data' tasks.

Maps a market to concrete free sources, fetches them, normalises into a DataBundle.
Tracks per-source cost and which datapoints influenced the price estimate.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx

from ..contracts import DataBundle, DataSourceUse, Market
from ..store.factory import build_repository
from ..store.repository import DataSourceUseRecord, Repository, TaskRecord, TrailEvent

log = logging.getLogger(__name__)

TOPIC_SOURCES: dict[str, list[str]] = {
    "sports.nba":   ["espn_scoreboard"],
    "sports.nfl":   ["espn_scoreboard"],
    "crypto.price": ["coingecko"],
    "chess":        ["lichess_fide"],
    "default":      [],
}


def _classify(m: Market) -> str:
    text = (m.question + " " + m.category).lower()
    if any(k in text for k in ["nba", "lakers", "celtics", "warriors", "knicks"]):
        return "sports.nba"
    if any(k in text for k in ["nfl", "super bowl", "patriots", "chiefs", "eagles"]):
        return "sports.nfl"
    if any(k in text for k in ["chess", "carlsen", "nakamura", "fide", "grandmaster",
                               "candidates", "gukesh", "nepomniachtchi", "ding liren",
                               "caruana", "firouzja", "world chess"]):
        return "chess"
    if any(k in text for k in ["bitcoin", "btc", "ethereum", "eth", "solana", "sol"]):
        if any(k in text for k in ["price", "reach", "above", "below", "$"]):
            return "crypto.price"
    return "default"


async def _fetch_coingecko(m: Market, http: httpx.AsyncClient) -> DataSourceUse:
    sym_match = re.search(r"\b(bitcoin|btc|ethereum|eth|solana|sol)\b", m.question.lower())
    if not sym_match:
        return DataSourceUse(source_name="coingecko", source_type="free",
                             acquisition_method="free", datapoints={})
    sym = sym_match.group(1)
    cg_id = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana"}.get(sym, sym)
    try:
        r = await http.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd", "include_24hr_change": "true"},
        )
        r.raise_for_status()
        data = r.json().get(cg_id, {})
        datapoints = {
            "price_usd": data.get("usd"),
            "change_24h_pct": data.get("usd_24h_change"),
            "symbol": cg_id,
        }
        return DataSourceUse(
            source_name="coingecko",
            source_url=f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}",
            source_type="free",
            acquisition_method="free",
            datapoints=datapoints,
            cost_usd=0.0,
            influenced_price=True,
            influenced_note=f"{cg_id} spot price used for fair-value anchor",
        )
    except Exception as e:
        log.debug("coingecko failed: %s", e)
        return DataSourceUse(source_name="coingecko", source_type="free",
                             acquisition_method="free", datapoints={})


async def _fetch_espn(m: Market, http: httpx.AsyncClient) -> DataSourceUse:
    # ESPN's public scoreboard endpoint; returns recent NBA scores.
    try:
        r = await http.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        events = data.get("events", [])
        games = [
            {
                "name": e.get("name"),
                "status": e.get("status", {}).get("type", {}).get("description"),
                "competitors": [
                    {"team": c.get("team", {}).get("displayName"), "score": c.get("score")}
                    for c in e.get("competitions", [{}])[0].get("competitors", [])
                ],
            }
            for e in events[:5]
        ]
        return DataSourceUse(
            source_name="espn_nba_scoreboard",
            source_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
            source_type="free",
            acquisition_method="free",
            datapoints={"games": games},
            cost_usd=0.0,
            influenced_price=bool(games),
            influenced_note="Live/recent NBA scores used for context",
        )
    except Exception as e:
        log.debug("espn scoreboard failed: %s", e)
        return DataSourceUse(source_name="espn_nba_scoreboard", source_type="free",
                             acquisition_method="free", datapoints={})


_CHESS_STOP = {
    "world", "chess", "championship", "championships", "fide", "candidates", "tournament",
    "cup", "masters", "open", "grand", "prix", "tour", "will", "the", "win", "wins", "beat",
    "champion", "grandmaster", "match", "final", "finals", "title", "norway", "global",
    "league", "super", "united", "states", "olympiad", "blitz", "rapid", "classical",
    "round", "game", "freestyle", "speed",
}


def _chess_candidate_names(question: str) -> list[str]:
    """Pull likely player-name phrases (runs of capitalised words) from a question."""
    names: list[str] = []
    for run in re.findall(r"[A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+)*", question):
        words = [w for w in run.split() if w.lower() not in _CHESS_STOP]
        phrase = " ".join(words).strip()
        if len(phrase) >= 3 and phrase not in names:
            names.append(phrase)
    return names[:4]


async def _fetch_chess(m: Market, http: httpx.AsyncClient) -> DataSourceUse:
    """FIDE ratings for the players named in a chess market (via Lichess's FIDE mirror).

    Chess has a clean Elo -> win-probability model, so when two rated players are
    found we attach an Elo-implied head-to-head probability as a fair-value anchor.
    """
    players: list[dict] = []
    seen: set[int] = set()
    for name in _chess_candidate_names(m.question):
        try:
            r = await http.get("https://lichess.org/api/fide/player", params={"q": name})
            r.raise_for_status()
            results = r.json()
        except Exception as e:
            log.debug("lichess fide search failed for %r: %s", name, e)
            continue
        if not isinstance(results, list) or not results:
            continue
        p = results[0]
        if p.get("id") in seen or not p.get("standard"):
            continue
        seen.add(p.get("id"))
        players.append({
            "query": name, "name": p.get("name"), "fide_id": p.get("id"),
            "title": p.get("title"), "federation": p.get("federation"),
            "standard": p.get("standard"), "rapid": p.get("rapid"), "blitz": p.get("blitz"),
        })

    datapoints: dict = {"players": players}
    note = ""
    if len(players) >= 2:
        ra, rb = float(players[0]["standard"]), float(players[1]["standard"])
        p_a = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        datapoints["elo_head_to_head"] = {
            players[0]["name"]: round(p_a, 4),
            players[1]["name"]: round(1.0 - p_a, 4),
            "formula": "1/(1+10^((Rb-Ra)/400)) on FIDE standard ratings",
        }
        note = (f"FIDE standard {players[0]['name']} {ra:.0f} vs {players[1]['name']} {rb:.0f}"
                f" -> Elo win prob {p_a:.1%}")
    elif players:
        note = f"FIDE ratings for {', '.join(p['name'] for p in players)}"

    return DataSourceUse(
        source_name="lichess_fide",
        source_url="https://lichess.org/api/fide/player",
        source_type="free",
        acquisition_method="free",
        datapoints=datapoints,
        cost_usd=0.0,
        influenced_price=bool(players),
        influenced_note=note,
    )


async def gather_data(market: Market, decision_id: str, repo: Repository) -> DataBundle:
    topic = _classify(market)
    sources_to_fetch = TOPIC_SOURCES.get(topic, TOPIC_SOURCES["default"])

    bundle_sources: list[DataSourceUse] = []
    payload: dict = {"topic": topic}

    async with httpx.AsyncClient(timeout=15.0) as http:
        for src in sources_to_fetch:
            if src == "coingecko":
                use = await _fetch_coingecko(market, http)
            elif src == "espn_scoreboard":
                use = await _fetch_espn(market, http)
            elif src == "lichess_fide":
                use = await _fetch_chess(market, http)
            else:
                continue

            bundle_sources.append(use)

            # Persist DataSourceUse record.
            await repo.append_data_source_use(DataSourceUseRecord(
                market_id=market.id,
                decision_id=decision_id,
                source_name=use.source_name,
                source_url=use.source_url,
                source_type=use.source_type,
                datapoints=use.datapoints,
                acquisition_method=use.acquisition_method,
                cost_usd=use.cost_usd,
                influenced_price=use.influenced_price,
                influenced_note=use.influenced_note,
            ))

            # Emit trail event per source.
            method_label = use.acquisition_method
            cost_label = f" (${use.cost_usd:.4f})" if use.cost_usd > 0 else " (free)"
            await repo.append_trail_event(TrailEvent(
                decision_id=decision_id,
                market_id=market.id,
                agent="data",
                text=f"Pulled {use.source_name} via {method_label}{cost_label}",
                payload={"source": use.model_dump(), "topic": topic},
            ))

            if use.datapoints:
                payload[use.source_name] = use.datapoints

    return DataBundle(market_id=market.id, sources=bundle_sources, payload=payload)


async def _worker_loop() -> None:
    repo = build_repository()
    await repo.init()
    pid = os.getpid()
    log.info("data worker started (pid=%d)", pid)

    while True:
        task = await repo.claim_task("fetch_data", pid)
        if task is None:
            await asyncio.sleep(0.5)
            continue
        log.info("data: claimed task %s", task.id)
        try:
            market = Market(**task.input_payload["market"])
            decision_id = task.decision_id
            bundle = await gather_data(market, decision_id, repo)
            await repo.complete_task(task.id, bundle.model_dump(mode="json"))
            log.info("data: completed task %s — %d sources", task.id, len(bundle.sources))
        except Exception as e:
            log.exception("data: task %s failed", task.id)
            await repo.fail_task(task.id, str(e))


def main() -> None:
    from .._console import force_utf8
    force_utf8()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s [data] %(levelname)s %(message)s")
    asyncio.run(_worker_loop())


if __name__ == "__main__":
    main()
