"""Correlated Market & Arbitrage Agent — P1 stub.

Interface defined; implementation deferred until MVP is validated.
Polls task queue for 'arbitrage' tasks, detects structural contradictions
across discovered markets, and emits arbitrage-signal TrailEvents.
"""
from __future__ import annotations

import asyncio
import logging
import os

from ..store.factory import build_repository
from ..store.repository import Repository, TaskRecord, TrailEvent

log = logging.getLogger(__name__)


async def run_arbitrage(task: TaskRecord, repo: Repository) -> dict:
    """Stub: log that the task was received and return an empty signal."""
    await repo.append_trail_event(TrailEvent(
        decision_id=task.decision_id,
        market_id=task.market_id,
        agent="arbitrage",
        text="Arbitrage scan: P1 stub — no signals emitted",
        payload={"candidates": task.input_payload.get("candidates", [])},
    ))
    return {"signals": []}


async def _worker_loop() -> None:
    repo = build_repository()
    await repo.init()
    pid = os.getpid()
    log.info("arbitrage worker started (pid=%d) [P1 stub]", pid)

    while True:
        task = await repo.claim_task("arbitrage", pid)
        if task is None:
            await asyncio.sleep(2.0)
            continue
        log.info("arbitrage: claimed task %s", task.id)
        try:
            output = await run_arbitrage(task, repo)
            await repo.complete_task(task.id, output)
        except Exception as e:
            log.exception("arbitrage: task %s failed", task.id)
            await repo.fail_task(task.id, str(e))


def main() -> None:
    from .._console import force_utf8
    force_utf8()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s [arbitrage] %(levelname)s %(message)s")
    asyncio.run(_worker_loop())


if __name__ == "__main__":
    main()
