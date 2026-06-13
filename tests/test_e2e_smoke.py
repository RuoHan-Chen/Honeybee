"""End-to-end smoke test of the full pipeline (data -> research -> risk -> trail).

Run: python -m tests.test_e2e_smoke
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.data import gather_data
from src.agents.research import run_research
from src.contracts import Market, ResearchResult, Vertical
from src.risk.sizing import compute_sizing
from src.store.repository import TaskRecord
from src.store.sqlite_repo import SqliteRepository


async def e2e() -> None:
    repo = SqliteRepository("./var/e2e_test.db")
    await repo.init()
    with open("config/mandate.yaml") as f:
        mandate = yaml.safe_load(f)

    m = Market(
        id="demo1", slug="demo", url="https://polymarket.com/event/demo",
        question="Will Bitcoin close above $150k by end of 2026?",
        category="crypto", vertical=Vertical.macro,
        yes_price=0.30, no_price=0.70, spread=0.02, liquidity=5000, volume_24h=800,
    )
    decision_id = uuid4().hex

    bundle = await gather_data(m, decision_id, repo)
    print(f"Data sources fetched: {len(bundle.sources)}")

    task = TaskRecord(
        id=uuid4().hex, task_type="research", decision_id=decision_id, market_id=m.id,
        input_payload={"market": m.model_dump(mode="json"),
                       "bundle": bundle.model_dump(mode="json")},
    )
    ro = await run_research(task, repo, mandate)
    print(f"Research: fair={ro.get('fair_value'):.3f} conf={ro.get('confidence'):.2f} "
          f"cost=${ro.get('token_cost_usd'):.5f} abstain={ro.get('abstain')}")

    research = ResearchResult(**ro)
    sizing = compute_sizing(
        m, research, daily_loss_so_far=0, bankroll_usd=1000,
        kelly_fraction=0.25, max_exposure_per_market_usd=25, daily_loss_limit_usd=100,
        min_edge=0.05, min_confidence=0.55, max_liquidity_fraction=0.05,
    )
    print(f"Decision: {sizing.decision.side.value} size=${sizing.decision.size_usd:.2f} "
          f"reason={sizing.decision.reason}")

    trail = await repo.get_decision_trail(decision_id)
    print(f"\n--- Decision trail ({len(trail)} events) ---")
    for ev in trail:
        print(f"  [{ev.agent}] {ev.text}")


if __name__ == "__main__":
    asyncio.run(e2e())
