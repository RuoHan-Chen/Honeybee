"""Backtest / calibration harness.

Replays resolved historical markets through the Research Agent and compares
its fair values to actual resolutions. Outputs:
  - Calibration report: of markets priced at ~X%, how many resolved YES
  - Estimated expected value

Run with:  python -m src.backtest.harness

This is the gate: do not use --live until calibration looks sane.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from ..agents.research import run_research
from ..contracts import DataBundle, Market, Vertical
from ..store.repository import TaskRecord
from ..store.factory import build_repository

log = logging.getLogger(__name__)
_MANDATE_PATH = Path(__file__).resolve().parents[2] / "config" / "mandate.yaml"

# Sample resolved markets for backtesting — replace with real historical data.
_SAMPLE_RESOLVED: list[dict] = [
    {
        "id": "bt-001", "slug": "bt-001", "url": "",
        "question": "Will Bitcoin exceed $100,000 before end of 2024?",
        "category": "crypto", "vertical": "macro",
        "yes_price": 0.45, "no_price": 0.55, "spread": 0.0,
        "liquidity": 5000.0, "volume_24h": 800.0,
        "end_date": "2024-12-31T00:00:00+00:00",
        "order_book_enabled": True,
        "resolved_yes": True,
    },
    {
        "id": "bt-002", "slug": "bt-002", "url": "",
        "question": "Will the Fed cut rates in November 2024?",
        "category": "macro", "vertical": "macro",
        "yes_price": 0.70, "no_price": 0.30, "spread": 0.0,
        "liquidity": 8000.0, "volume_24h": 1200.0,
        "end_date": "2024-11-30T00:00:00+00:00",
        "order_book_enabled": True,
        "resolved_yes": True,
    },
    {
        "id": "bt-003", "slug": "bt-003", "url": "",
        "question": "Will the Lakers win the 2024 NBA championship?",
        "category": "sports", "vertical": "sports",
        "yes_price": 0.15, "no_price": 0.85, "spread": 0.0,
        "liquidity": 3000.0, "volume_24h": 500.0,
        "end_date": "2024-06-30T00:00:00+00:00",
        "order_book_enabled": True,
        "resolved_yes": False,
    },
]


def _bucket(p: float, n_buckets: int = 10) -> int:
    return min(int(p * n_buckets), n_buckets - 1)


async def run_backtest(sample_markets: list[dict] | None = None) -> None:
    repo = build_repository()
    await repo.init()

    with open(_MANDATE_PATH) as f:
        mandate = yaml.safe_load(f)

    markets_to_test = sample_markets or _SAMPLE_RESOLVED
    results: list[dict] = []

    for m_raw in markets_to_test:
        resolved_yes: bool = m_raw.pop("resolved_yes", False)
        resolved_value = 1.0 if resolved_yes else 0.0

        # Parse end_date
        end_date_str = m_raw.get("end_date")
        end_date = datetime.fromisoformat(end_date_str) if end_date_str else None
        m_raw["end_date"] = end_date
        m_raw["vertical"] = Vertical(m_raw.get("vertical", "other"))

        market = Market(**{k: v for k, v in m_raw.items()
                          if k in Market.model_fields})

        decision_id = uuid4().hex
        bundle = DataBundle(market_id=market.id, sources=[], payload={})

        task = TaskRecord(
            id=uuid4().hex,
            task_type="research",
            decision_id=decision_id,
            market_id=market.id,
            input_payload={
                "market": market.model_dump(mode="json"),
                "bundle": bundle.model_dump(mode="json"),
            },
        )

        try:
            research_output = await run_research(task, repo, mandate)
        except Exception as e:
            log.warning("backtest research failed for %s: %s", market.id, e)
            continue

        fair_value = research_output.get("fair_value", market.yes_price)
        confidence = research_output.get("confidence", 0.0)
        edge = fair_value - market.yes_price if resolved_yes else (1 - fair_value) - market.no_price
        was_right = (fair_value > 0.5) == resolved_yes

        results.append({
            "market_id": market.id,
            "question": market.question[:60],
            "market_price": market.yes_price,
            "fair_value": fair_value,
            "confidence": confidence,
            "resolved_yes": resolved_yes,
            "resolved_value": resolved_value,
            "edge": edge,
            "was_right": was_right,
            "cost_usd": research_output.get("token_cost_usd", 0.0),
        })

    _print_report(results)


def _print_report(results: list[dict]) -> None:
    if not results:
        print("No results to report.")
        return

    print("\n" + "=" * 70)
    print("BACKTEST CALIBRATION REPORT")
    print("=" * 70)

    # Per-result table
    print(f"\n{'Question':<40} {'MktP':>6} {'Fair':>6} {'Conf':>6} {'Res':>5} {'Right':>6}")
    print("-" * 70)
    for r in results:
        print(
            f"{r['question']:<40} "
            f"{r['market_price']:>6.3f} "
            f"{r['fair_value']:>6.3f} "
            f"{r['confidence']:>6.2f} "
            f"{'YES' if r['resolved_yes'] else 'NO':>5} "
            f"{'✓' if r['was_right'] else '✗':>6}"
        )

    # Calibration buckets
    print("\nCALIBRATION (predicted probability vs actual resolution rate)")
    buckets: dict[int, list[float]] = defaultdict(list)
    for r in results:
        b = _bucket(r["fair_value"])
        buckets[b].append(r["resolved_value"])
    print(f"{'Bucket':>10} {'N':>5} {'Predicted':>12} {'Actual':>10}")
    for b in sorted(buckets):
        lo = b / 10
        hi = (b + 1) / 10
        vals = buckets[b]
        predicted = (lo + hi) / 2
        actual = statistics.mean(vals)
        print(f"  {lo:.1f}-{hi:.1f}   {len(vals):>5}   {predicted:>10.3f}   {actual:>8.3f}")

    # Summary stats
    n = len(results)
    accuracy = sum(r["was_right"] for r in results) / n if n else 0
    avg_edge = statistics.mean(r["edge"] for r in results) if results else 0
    total_cost = sum(r["cost_usd"] for r in results)
    avg_confidence = statistics.mean(r["confidence"] for r in results) if results else 0

    print(f"\nSUMMARY")
    print(f"  Markets tested:   {n}")
    print(f"  Directional acc:  {accuracy:.1%}")
    print(f"  Avg edge:         {avg_edge:+.4f}")
    print(f"  Avg confidence:   {avg_confidence:.3f}")
    print(f"  Total LLM cost:   ${total_cost:.5f}")
    print(f"  Cost per market:  ${total_cost/n if n else 0:.5f}")
    print("=" * 70 + "\n")

    if accuracy < 0.55:
        print("WARNING: Accuracy below 55% — do NOT enable --live until calibration improves.")
    else:
        print("Calibration looks reasonable — review edge distribution before enabling --live.")


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s [backtest] %(levelname)s %(message)s")
    asyncio.run(run_backtest())


if __name__ == "__main__":
    main()
