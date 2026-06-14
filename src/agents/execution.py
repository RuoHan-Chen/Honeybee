"""Execution & Risk Agent — separate process, polls task queue for 'execute' tasks.

Computes edge, runs Kelly sizing + risk checks, submits via Wallet,
persists RiskDecisionRecord + FillRecord + TrailEvents.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

from ..contracts import Market, ResearchResult, TradeSide
from ..risk.sizing import compute_sizing
from ..store.repository import (
    FillRecord,
    Repository,
    RiskDecisionRecord,
    TaskRecord,
    TrailEvent,
)
from ..store.factory import build_repository
from ..venue.wallet import PaperWallet, build_wallet

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

log = logging.getLogger(__name__)
_MANDATE_PATH = Path(__file__).resolve().parents[2] / "config" / "mandate.yaml"


def _load_mandate() -> dict:
    with open(_MANDATE_PATH) as f:
        return yaml.safe_load(f)


async def run_execution(task: TaskRecord, repo: Repository, mandate: dict, live: bool) -> dict:
    market = Market(**task.input_payload["market"])
    research = ResearchResult(**task.input_payload["research"])
    decision_id = task.decision_id

    daily_loss = await repo.get_daily_loss(date.today().isoformat())

    sizing = compute_sizing(
        market=market,
        research=research,
        daily_loss_so_far=daily_loss,
        bankroll_usd=float(mandate.get("bankroll_usd", 1000)),
        kelly_fraction=float(mandate.get("kelly_fraction", 0.25)),
        max_exposure_per_market_usd=float(mandate.get("max_exposure_per_market_usd", 25)),
        daily_loss_limit_usd=float(mandate.get("daily_loss_limit_usd", 100)),
        min_edge=float(mandate.get("min_edge", 0.05)),
        min_confidence=float(mandate.get("min_confidence", 0.55)),
        max_liquidity_fraction=float(mandate.get("max_liquidity_fraction", 0.05)),
    )

    decision = sizing.decision
    executed = False
    fill_data: dict = {}

    # Persist risk decision before attempting fill.
    await repo.upsert_risk_decision(RiskDecisionRecord(
        decision_id=decision_id,
        market_id=market.id,
        market_price=sizing.market_price,
        fair_value=research.fair_value,
        edge=decision.edge,
        kelly_inputs=sizing.kelly_inputs,
        size_usd=decision.size_usd,
        limit_price=decision.limit_price,
        risk_checks=sizing.risk_checks,
        slippage_estimate=sizing.slippage_estimate,
        side=decision.side.value,
        executed=False,
        reason=decision.reason,
    ))

    if decision.side == TradeSide.SKIP:
        await repo.append_trail_event(TrailEvent(
            decision_id=decision_id,
            market_id=market.id,
            agent="execution",
            text=f"Skipped: {decision.reason}",
            payload={"risk_checks": sizing.risk_checks, "side": "SKIP"},
        ))
        return {"side": "SKIP", "reason": decision.reason, "executed": False}

    # Trail event for the sizing decision.
    await repo.append_trail_event(TrailEvent(
        decision_id=decision_id,
        market_id=market.id,
        agent="execution",
        text=(
            f"Edge {decision.edge*100:.1f}pts → Kelly size ${decision.size_usd:.2f}, "
            f"limit={decision.limit_price:.4f} — submitting {decision.side.value}"
        ),
        payload={
            "side": decision.side.value,
            "size_usd": decision.size_usd,
            "limit_price": decision.limit_price,
            "edge": decision.edge,
            "kelly_inputs": sizing.kelly_inputs,
            "risk_checks": sizing.risk_checks,
        },
    ))

    wallet = build_wallet(live=live)
    fill = await wallet.submit(decision, sizing.market_price)

    if fill:
        executed = True
        await repo.append_fill(FillRecord(
            market_id=market.id,
            decision_id=decision_id,
            side=fill.side.value,
            size_usd=fill.size_usd,
            avg_price=fill.avg_price,
            tx_ref=fill.tx_ref,
            paper=fill.paper,
            timestamp=fill.timestamp,
        ))
        # Update risk decision to mark executed.
        await repo.upsert_risk_decision(RiskDecisionRecord(
            decision_id=decision_id,
            market_id=market.id,
            market_price=sizing.market_price,
            fair_value=research.fair_value,
            edge=decision.edge,
            kelly_inputs=sizing.kelly_inputs,
            size_usd=decision.size_usd,
            limit_price=decision.limit_price,
            risk_checks=sizing.risk_checks,
            slippage_estimate=sizing.slippage_estimate,
            side=decision.side.value,
            executed=True,
            reason=decision.reason,
        ))
        paper_label = "[paper]" if fill.paper else "[LIVE]"
        await repo.append_trail_event(TrailEvent(
            decision_id=decision_id,
            market_id=market.id,
            agent="execution",
            text=(
                f"{paper_label} Filled {fill.side.value} ${fill.size_usd:.2f} "
                f"@ {fill.avg_price:.4f} — tx={fill.tx_ref}"
            ),
            payload=fill.model_dump(mode="json"),
        ))
        fill_data = fill.model_dump(mode="json")

    return {
        "side": decision.side.value,
        "reason": decision.reason,
        "executed": executed,
        "fill": fill_data,
    }


async def _worker_loop(live: bool = False) -> None:
    repo = build_repository()
    await repo.init()
    mandate = _load_mandate()
    pid = os.getpid()
    log.info("execution worker started (pid=%d, live=%s)", pid, live)

    while True:
        task = await repo.claim_task("execute", pid)
        if task is None:
            await asyncio.sleep(0.5)
            continue
        log.info("execution: claimed task %s (decision=%s)", task.id, task.decision_id)
        try:
            output = await run_execution(task, repo, mandate, live)
            await repo.complete_task(task.id, output)
            log.info("execution: completed task %s side=%s executed=%s",
                     task.id, output.get("side"), output.get("executed"))
        except Exception as e:
            log.exception("execution: task %s failed", task.id)
            await repo.fail_task(task.id, str(e))


def main() -> None:
    from .._console import force_utf8
    force_utf8()
    live = os.getenv("LIVE_TRADING", "false").lower() in ("1", "true", "yes")
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s [execution] %(levelname)s %(message)s")
    asyncio.run(_worker_loop(live=live))


if __name__ == "__main__":
    main()
