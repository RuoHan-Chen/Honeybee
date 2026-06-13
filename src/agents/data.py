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
    "default":      [],
}


def _classify(m: Market) -> str:
    text = (m.question + " " + m.category).lower()
    if any(k in text for k in ["nba", "lakers", "celtics", "warriors", "knicks"]):
        return "sports.nba"
    if any(k in text for k in ["nfl", "super bowl", "patriots", "chiefs", "eagles"]):
        return "sports.nfl"
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
