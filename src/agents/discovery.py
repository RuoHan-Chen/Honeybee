"""Market Discovery Agent — separate process, polls task queue for 'discover' tasks.

No LLM — purely mechanical filtering and scoring.
Writes MarketRecord + MarketSnapshot + TrailEvent per candidate.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..contracts import Market, Vertical
from ..store.factory import build_repository
from ..store.repository import (
    MarketRecord,
    MarketSnapshot,
    Repository,
    TaskRecord,
    TrailEvent,
)
from ..venue.kalshi import KalshiAdapter
from ..venue.polymarket import PolymarketAdapter

log = logging.getLogger(__name__)

_MANDATE_PATH = Path(__file__).resolve().parents[2] / "config" / "mandate.yaml"


def _load_mandate() -> dict:
    with open(_MANDATE_PATH) as f:
        return yaml.safe_load(f)


def _score(m: Market, hours_left: float) -> float:
    vol_score = math.log1p(m.volume_24h)
    time_decay = math.exp(-hours_left / (24 * 14))
    uncertainty = 1.0 - 2 * abs(m.yes_price - 0.5)
    return uncertainty * vol_score * (0.3 + time_decay)


async def run_discovery(task: TaskRecord, repo: Repository, mandate: dict) -> dict:
    """Execute one discovery cycle. Returns the list of candidates as serialisable dicts."""
    d = mandate.get("discovery", {})
    max_liq = float(d.get("max_liquidity_usd", 50_000))
    min_spread = float(d.get("min_spread", 0.02))
    min_vol = float(d.get("min_volume_24h_usd", 50))
    max_vol = float(d.get("max_volume_24h_usd", 50_000))
    min_hours = float(d.get("min_hours_to_resolution", 1))
    max_days = float(d.get("max_days_to_resolution", 365))
    top_n = int(d.get("top_n", 20))
    verticals_allowed = set(mandate.get("verticals", [v.value for v in Vertical]))

    # Pull from every configured venue; one venue failing must not sink the cycle.
    raw_markets: list[Market] = []
    for adapter in (PolymarketAdapter(), KalshiAdapter()):
        venue_name = getattr(adapter, "name", type(adapter).__name__)
        try:
            ms = await adapter.list_markets(limit=500)
            log.info("discovery: %s returned %d markets", venue_name, len(ms))
            raw_markets.extend(ms)
        except Exception as e:
            log.warning("discovery: %s list_markets failed: %s", venue_name, e)
        finally:
            await adapter.close()

    now = datetime.now(timezone.utc)
    candidates: list[tuple[Market, float, str]] = []

    for m in raw_markets:
        reasons: list[str] = []

        if not m.order_book_enabled:
            continue
        if m.vertical.value not in verticals_allowed:
            continue
        if m.liquidity > max_liq:
            continue
        # Gamma's summary endpoint reports spread≈0 (prices sum to ~1); only
        # enforce min_spread when we actually have a real (non-zero) spread.
        if m.spread > 0 and m.spread < min_spread:
            continue
        if not (min_vol <= m.volume_24h <= max_vol):
            continue
        if m.end_date is None:
            continue
        hours_left = (m.end_date - now).total_seconds() / 3600
        if hours_left < min_hours or hours_left / 24 > max_days:
            continue

        reasons.append(f"spread={m.spread:.3f}")
        reasons.append(f"vol24h=${m.volume_24h:,.0f}")
        reasons.append(f"liq=${m.liquidity:,.0f}")
        reasons.append(f"{hours_left:.0f}h to close")

        score = _score(m, hours_left)
        flagged_reason = "; ".join(reasons)
        candidates.append((m, score, flagged_reason))

    candidates.sort(key=lambda x: x[1], reverse=True)
    top = candidates[:top_n]

    log.info("discovery: %d / %d markets pass filter", len(top), len(raw_markets))

    # Persist and emit trail events.
    result_markets = []
    for m, score, flagged_reason in top:
        await repo.upsert_market(MarketRecord(
            market_id=m.id,
            slug=m.slug,
            url=m.url,
            question=m.question,
            category=m.category,
            vertical=m.vertical.value,
            yes_price=m.yes_price,
            no_price=m.no_price,
            spread=m.spread,
            liquidity=m.liquidity,
            volume_24h=m.volume_24h,
            end_date=m.end_date,
            order_book_enabled=m.order_book_enabled,
            flagged_reason=flagged_reason,
            discovery_score=score,
        ))
        await repo.append_snapshot(MarketSnapshot(
            market_id=m.id,
            yes_price=m.yes_price,
            no_price=m.no_price,
            spread=m.spread,
            liquidity=m.liquidity,
            volume_24h=m.volume_24h,
        ))
        await repo.append_trail_event(TrailEvent(
            decision_id=task.decision_id,
            market_id=m.id,
            agent="discovery",
            text=(
                f"Flagged {m.vertical.value} market: spread={m.spread:.3f}, "
                f"liq=${m.liquidity:,.0f}, vol=${m.volume_24h:,.0f}, score={score:.3f}"
            ),
            payload={"market": m.model_dump(mode="json"), "score": score, "flagged_reason": flagged_reason},
        ))
        result_markets.append(m.model_dump(mode="json"))

    return {"candidates": result_markets}


async def _worker_loop() -> None:
    repo = build_repository()
    await repo.init()
    mandate = _load_mandate()
    pid = os.getpid()
    log.info("discovery worker started (pid=%d)", pid)

    while True:
        task = await repo.claim_task("discover", pid)
        if task is None:
            await asyncio.sleep(1.0)
            continue
        log.info("discovery: claimed task %s (decision=%s)", task.id, task.decision_id)
        try:
            output = await run_discovery(task, repo, mandate)
            await repo.complete_task(task.id, output)
            log.info("discovery: completed task %s — %d candidates", task.id, len(output["candidates"]))
        except Exception as e:
            log.exception("discovery: task %s failed", task.id)
            await repo.fail_task(task.id, str(e))


def main() -> None:
    from .._console import force_utf8
    force_utf8()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s [discovery] %(levelname)s %(message)s")
    asyncio.run(_worker_loop())


if __name__ == "__main__":
    main()
