"""Run ONE full orchestrator cycle across real agent processes, then print
the reconstructed decision trail for the first executed/skipped market.

Run: python -m tests.test_one_cycle
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src._console import force_utf8
from src.orchestrator import Orchestrator
from src.store.sqlite_repo import SqliteRepository


async def main() -> None:
    force_utf8()
    orch = Orchestrator(live=False)
    await orch.repo.init()
    orch._spawn_agents()
    print("Agents spawned, waiting 2s for them to start polling...")
    await asyncio.sleep(2)

    print("Running one cycle...")
    await orch._cycle()

    orch._terminate_agents()
    print("\nAgents terminated. Reconstructing a decision trail...")

    # Find a decision_id that reached execution (risk decision exists).
    repo = SqliteRepository()
    import aiosqlite
    async with aiosqlite.connect(repo.path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT decision_id, market_id, side, executed, reason FROM risk_decisions "
            "ORDER BY created_at DESC LIMIT 5"
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        print("No risk decisions recorded this cycle.")
        return

    print(f"\nLast {len(rows)} risk decisions:")
    for r in rows:
        print(f"  {r['decision_id'][:12]} market={r['market_id'][:12]} "
              f"side={r['side']} executed={r['executed']} — {r['reason'][:60]}")

    # Show the full trail for the most recent one.
    target = rows[0]["decision_id"]
    trail = await repo.get_decision_trail(target)
    print(f"\n=== FULL DECISION TRAIL for {target} ===")
    for ev in trail:
        print(f"  [{ev.agent:>11}] {ev.text}")


if __name__ == "__main__":
    asyncio.run(main())
