"""Orchestrator — spawns all agent processes and drives the pipeline.

Architecture:
  - Each agent (discovery, data, research, execution, arbitrage) runs as a
    separate Python Process polling the SQLite task queue.
  - Orchestrator mints one decision_id per (market, cycle), enqueues tasks,
    and polls for results before advancing to the next stage.
  - Communication is entirely through the Repository (SQLite WAL mode).
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import signal
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .store.factory import build_repository
from .store.repository import Repository, TaskRecord, TrailEvent

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

log = logging.getLogger(__name__)

_MANDATE_PATH = Path(__file__).resolve().parents[1] / "config" / "mandate.yaml"
_POLL_INTERVAL = 0.5    # seconds between task-completion polls
_TASK_TIMEOUT = 120     # seconds before a task is considered hung


def _load_mandate() -> dict:
    with open(_MANDATE_PATH) as f:
        return yaml.safe_load(f)


# ── Agent process entry points ────────────────────────────────────────────────

def _run_discovery() -> None:
    from .agents.discovery import main
    main()


def _run_data() -> None:
    from .agents.data import main
    main()


def _run_research() -> None:
    from .agents.research import main
    main()


def _run_execution() -> None:
    from .agents.execution import main
    main()


def _run_arbitrage() -> None:
    from .agents.arbitrage import main
    main()


_AGENT_TARGETS = {
    "discovery": _run_discovery,
    "data": _run_data,
    "research": _run_research,
    "execution": _run_execution,
    "arbitrage": _run_arbitrage,
}


# ── Task helpers ──────────────────────────────────────────────────────────────

def _new_task(task_type: str, decision_id: str, market_id: str = "",
              input_payload: dict | None = None) -> TaskRecord:
    return TaskRecord(
        id=uuid.uuid4().hex,
        task_type=task_type,
        decision_id=decision_id,
        market_id=market_id,
        input_payload=input_payload or {},
        status="pending",
    )


async def _wait_for_task(repo: Repository, task_id: str,
                         timeout: float = _TASK_TIMEOUT) -> TaskRecord | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        t = await repo.get_task(task_id)
        if t and t.status in ("done", "failed"):
            return t
        await asyncio.sleep(_POLL_INTERVAL)
    log.warning("task %s timed out after %.0fs", task_id, timeout)
    return None


# ── Main orchestrator ─────────────────────────────────────────────────────────

class Orchestrator:
    def __init__(self, live: bool = False) -> None:
        self.live = live
        self.repo = build_repository()
        self.mandate = _load_mandate()
        self._processes: dict[str, multiprocessing.Process] = {}
        self._stop = asyncio.Event()

    def _spawn_agents(self) -> None:
        if self.live:
            os.environ["LIVE_TRADING"] = "true"
        for name, target in _AGENT_TARGETS.items():
            p = multiprocessing.Process(target=target, name=name, daemon=True)
            p.start()
            self._processes[name] = p
            log.info("spawned agent process: %s (pid=%d)", name, p.pid)

    def _health_check(self) -> None:
        """Restart any agent process that died unexpectedly."""
        for name, p in list(self._processes.items()):
            if not p.is_alive():
                log.warning("agent %s (pid=%d) died — restarting", name, p.pid)
                new_p = multiprocessing.Process(
                    target=_AGENT_TARGETS[name], name=name, daemon=True
                )
                new_p.start()
                self._processes[name] = new_p
                log.info("restarted agent %s (pid=%d)", name, new_p.pid)

    def _shutdown(self, *_: Any) -> None:
        log.info("shutdown signal received")
        self._stop.set()

    async def run(self) -> None:
        await self.repo.init()
        self._spawn_agents()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._shutdown)
            except NotImplementedError:
                pass  # Windows

        mode = "LIVE" if self.live else "PAPER"
        log.info("orchestrator started — mode=%s bankroll=$%.2f",
                 mode, self.mandate.get("bankroll_usd", 0))

        interval = int(self.mandate.get("loop_interval_sec", 60))
        while not self._stop.is_set():
            self._health_check()
            cycle_start = time.monotonic()
            try:
                await self._cycle()
            except Exception:
                log.exception("cycle failed")
            elapsed = time.monotonic() - cycle_start
            log.info("cycle complete in %.1fs — sleeping %ds", elapsed, interval)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0, interval - elapsed))
            except asyncio.TimeoutError:
                pass

        self._terminate_agents()

    def _terminate_agents(self) -> None:
        for name, p in self._processes.items():
            p.terminate()
            p.join(timeout=5)
            log.info("terminated agent %s", name)

    async def _cycle(self) -> None:
        # ── Step 1: Discovery ────────────────────────────────────────────────
        cycle_decision_id = uuid.uuid4().hex
        await self.repo.append_trail_event(TrailEvent(
            decision_id=cycle_decision_id,
            market_id="",
            agent="orchestrator",
            text=f"Cycle start — decision_id={cycle_decision_id}",
            payload={"live": self.live},
        ))

        discovery_task = _new_task("discover", cycle_decision_id)
        await self.repo.enqueue_task(discovery_task)
        log.info("enqueued discovery task %s", discovery_task.id)

        completed = await _wait_for_task(self.repo, discovery_task.id)
        if not completed or completed.status == "failed":
            log.error("discovery failed: %s", completed.error if completed else "timeout")
            return

        candidates: list[dict] = completed.output_payload.get("candidates", [])
        log.info("discovery returned %d candidates", len(candidates))

        if not candidates:
            return

        # ── Step 2: For each candidate, fetch data + research + execute ──────
        cycle_cost = 0.0
        for market_dict in candidates:
            market_id = market_dict.get("id", "")
            decision_id = uuid.uuid4().hex

            await self.repo.append_trail_event(TrailEvent(
                decision_id=decision_id,
                market_id=market_id,
                agent="orchestrator",
                text=f"Evaluating: {market_dict.get('question', '')[:80]}",
                payload={"market_id": market_id, "yes_price": market_dict.get("yes_price"),
                         "no_price": market_dict.get("no_price")},
            ))

            # 2a. Fetch data
            data_task = _new_task("fetch_data", decision_id, market_id,
                                  input_payload={"market": market_dict})
            await self.repo.enqueue_task(data_task)
            data_done = await _wait_for_task(self.repo, data_task.id)
            if not data_done or data_done.status == "failed":
                log.warning("data fetch failed for market %s", market_id)
                bundle = {"market_id": market_id, "sources": [], "payload": {}}
            else:
                bundle = data_done.output_payload

            # 2b. Research
            research_task = _new_task("research", decision_id, market_id,
                                      input_payload={"market": market_dict, "bundle": bundle})
            await self.repo.enqueue_task(research_task)
            research_done = await _wait_for_task(self.repo, research_task.id)
            if not research_done or research_done.status == "failed":
                log.warning("research failed for market %s", market_id)
                continue

            research_result = research_done.output_payload
            cycle_cost += research_result.get("token_cost_usd", 0.0)

            # 2c. Execute / risk
            exec_task = _new_task("execute", decision_id, market_id,
                                  input_payload={"market": market_dict,
                                                 "research": research_result})
            await self.repo.enqueue_task(exec_task)
            exec_done = await _wait_for_task(self.repo, exec_task.id)
            if not exec_done or exec_done.status == "failed":
                log.warning("execution failed for market %s", market_id)
                continue

            side = exec_done.output_payload.get("side", "SKIP")
            executed = exec_done.output_payload.get("executed", False)
            log.info("market %s → side=%s executed=%s", market_id[:12], side, executed)

        # ── Step 3: Arbitrage scan (P1 stub) ─────────────────────────────────
        arb_task = _new_task("arbitrage", cycle_decision_id, "",
                             input_payload={"candidates": candidates})
        await self.repo.enqueue_task(arb_task)

        # ── Step 4: Circuit breaker check ─────────────────────────────────────
        today = date.today().isoformat()
        daily_loss = await self.repo.get_daily_loss(today)
        limit = float(self.mandate.get("daily_loss_limit_usd", 100))
        if daily_loss <= -limit:
            log.critical("CIRCUIT_BREAKER tripped — daily loss $%.2f exceeds limit $%.2f. HALTING.",
                         daily_loss, limit)
            await self.repo.append_trail_event(TrailEvent(
                decision_id=cycle_decision_id,
                market_id="",
                agent="orchestrator",
                text=f"CIRCUIT_BREAKER: daily loss ${daily_loss:.2f} hit limit ${limit:.2f} — halted",
                payload={"daily_loss": daily_loss, "limit": limit},
            ))
            self._stop.set()

        await self.repo.append_trail_event(TrailEvent(
            decision_id=cycle_decision_id,
            market_id="",
            agent="orchestrator",
            text=f"Cycle end — LLM cost=${cycle_cost:.5f}, daily_loss=${daily_loss:.2f}",
            payload={"cycle_cost_usd": cycle_cost, "daily_loss": daily_loss,
                     "candidates_evaluated": len(candidates)},
        ))
        log.info("cycle LLM cost=$%.5f  daily_pnl=$%.2f", cycle_cost, daily_loss)
