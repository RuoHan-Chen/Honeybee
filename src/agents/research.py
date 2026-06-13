"""Research Agent — separate process, polls task queue for 'research' tasks.

Two-pass Anthropic-only LLM pipeline:
  1. Cheap triage (haiku) — is this worth deep analysis?
  2. Deep analysis (sonnet) — calibrated fair value + source attribution.

Writes ResearchRecord + SourceAttribution + TrailEvents.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

from ..contracts import DataBundle, Market, ResearchResult, SourceAttribution
from ..store.repository import (
    ResearchRecord,
    SourceAttributionRecord,
    TaskRecord,
    TrailEvent,
)
from ..store.factory import build_repository
from ..store.repository import Repository

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

log = logging.getLogger(__name__)
_MANDATE_PATH = Path(__file__).resolve().parents[2] / "config" / "mandate.yaml"


def _load_mandate() -> dict:
    with open(_MANDATE_PATH) as f:
        return yaml.safe_load(f)


_SYSTEM_TRIAGE = """You are a triage analyst for a prediction-market trading agent.
Given a market with current prices, decide whether it merits deeper research.
Return ONLY a JSON object:
{
  "worth_deep_analysis": bool,
  "quick_fair_value": float (0..1, probability YES resolves),
  "rationale": "one sentence"
}
A market merits deep analysis if there is plausibly >5% edge available."""

_SYSTEM_DEEP = """You are a quantitative analyst for a long-tail prediction-market trading agent.
You will receive the market question, current prices, and structured context from data sources.
Return ONLY a JSON object:
{
  "fair_value": float (0..1, calibrated probability YES resolves),
  "confidence": float (0..1, how certain you are),
  "rationale": "2-3 sentence explanation",
  "source_attributions": [
    {"source_name": str, "fair_value_delta": float, "note": str}
  ]
}
Be calibrated. If you have no real edge, return a fair_value near current market price
and confidence < 0.55. Never invent sources."""


def _safe_json(text: str) -> dict:
    text = text.strip().strip("`")
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        return json.loads(text)
    except Exception:
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except Exception:
            return {}


def _market_brief(m: Market) -> str:
    close = m.end_date.isoformat() if m.end_date else "unknown"
    return (
        f"Question: {m.question}\n"
        f"YES price: {m.yes_price:.3f}  NO price: {m.no_price:.3f}\n"
        f"Spread: {m.spread:.3f}  Liquidity: ${m.liquidity:,.0f}  Vol24h: ${m.volume_24h:,.0f}\n"
        f"Closes: {close}\n"
        f"Category: {m.category}  Vertical: {m.vertical.value}"
    )


def _bundle_context(bundle: DataBundle) -> str:
    if not bundle.payload:
        return "(no external data available)"
    lines = []
    for source, data in bundle.payload.items():
        if source == "topic":
            continue
        lines.append(f"[{source}] {json.dumps(data, default=str)}")
    return "\n".join(lines) or "(no external data available)"


def _estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    if "haiku" in model:
        return in_tokens * 1e-6 + out_tokens * 5e-6
    if "sonnet" in model:
        return in_tokens * 3e-6 + out_tokens * 15e-6
    return 0.0


async def run_research(
    task: TaskRecord,
    repo: Repository,
    mandate: dict,
) -> dict:
    market = Market(**task.input_payload["market"])
    bundle = DataBundle(**task.input_payload["bundle"])
    decision_id = task.decision_id

    llm_cfg = mandate.get("llm", {})
    triage_model = llm_cfg.get("triage_model", "claude-haiku-4-5-20251001")
    deep_model = llm_cfg.get("routine_model", "claude-sonnet-4-6")
    max_usd = float(llm_cfg.get("max_usd_per_loop", 0.5))
    min_confidence = float(mandate.get("min_confidence", 0.55))

    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    total_cost = 0.0
    prior_fair_value = market.yes_price

    # ── Pass 1: cheap triage ──────────────────────────────────────────────────
    triage_resp = await client.messages.create(
        model=triage_model,
        system=_SYSTEM_TRIAGE,
        messages=[{"role": "user", "content": _market_brief(market)}],
        max_tokens=200,
        temperature=0.1,
    )
    triage_text = "".join(b.text for b in triage_resp.content if hasattr(b, "text"))
    triage_cost = _estimate_cost(triage_model, triage_resp.usage.input_tokens, triage_resp.usage.output_tokens)
    total_cost += triage_cost
    triage_data = _safe_json(triage_text)

    worth_deep = bool(triage_data.get("worth_deep_analysis", False))
    quick_fair = float(triage_data.get("quick_fair_value", market.yes_price))

    await repo.append_trail_event(TrailEvent(
        decision_id=decision_id,
        market_id=market.id,
        agent="research",
        text=(
            f"Triage ({triage_model}): worth_deep={worth_deep}, "
            f"quick_fair={quick_fair:.3f} (cost=${triage_cost:.5f})"
        ),
        payload={"triage": triage_data, "model": triage_model, "cost_usd": triage_cost},
    ))

    if not worth_deep or total_cost >= max_usd:
        result = ResearchResult(
            market_id=market.id,
            prior_fair_value=prior_fair_value,
            fair_value=quick_fair,
            confidence=0.40,
            rationale=triage_data.get("rationale", "triage-only, insufficient edge detected"),
            abstain=True,
            token_cost_usd=total_cost,
            model=triage_model,
        )
        await _persist(result, decision_id, market, repo)
        return result.model_dump(mode="json")

    # ── Pass 2: deep analysis ─────────────────────────────────────────────────
    context = _bundle_context(bundle)
    deep_prompt = _market_brief(market) + "\n\nContext from data sources:\n" + context

    deep_resp = await client.messages.create(
        model=deep_model,
        system=_SYSTEM_DEEP,
        messages=[{"role": "user", "content": deep_prompt}],
        max_tokens=600,
        temperature=0.1,
    )
    deep_text = "".join(b.text for b in deep_resp.content if hasattr(b, "text"))
    deep_cost = _estimate_cost(deep_model, deep_resp.usage.input_tokens, deep_resp.usage.output_tokens)
    total_cost += deep_cost
    deep_data = _safe_json(deep_text)

    fair_value = float(deep_data.get("fair_value", quick_fair))
    fair_value = max(0.01, min(0.99, fair_value))
    confidence = float(deep_data.get("confidence", 0.5))
    rationale = str(deep_data.get("rationale", ""))
    raw_attributions = deep_data.get("source_attributions") or []

    attributions = [
        SourceAttribution(
            source_name=a.get("source_name", "unknown"),
            fair_value_delta=float(a.get("fair_value_delta", 0.0)),
            note=str(a.get("note", "")),
        )
        for a in raw_attributions
    ]

    # Trail events for each attribution.
    for attr in attributions:
        if abs(attr.fair_value_delta) >= 0.01:
            direction = "+" if attr.fair_value_delta > 0 else ""
            await repo.append_trail_event(TrailEvent(
                decision_id=decision_id,
                market_id=market.id,
                agent="research",
                text=(
                    f"{attr.source_name} shifted fair value "
                    f"{prior_fair_value:.3f} → {prior_fair_value + attr.fair_value_delta:.3f} "
                    f"({direction}{attr.fair_value_delta:+.3f}): {attr.note}"
                ),
                payload=attr.model_dump(),
            ))

    await repo.append_trail_event(TrailEvent(
        decision_id=decision_id,
        market_id=market.id,
        agent="research",
        text=(
            f"Deep analysis ({deep_model}): fair_value={fair_value:.3f}, "
            f"confidence={confidence:.2f}, cost=${deep_cost:.5f}"
        ),
        payload={"fair_value": fair_value, "confidence": confidence,
                 "rationale": rationale, "model": deep_model, "cost_usd": deep_cost},
    ))

    result = ResearchResult(
        market_id=market.id,
        prior_fair_value=prior_fair_value,
        fair_value=fair_value,
        confidence=confidence,
        rationale=rationale,
        source_attributions=attributions,
        abstain=confidence < min_confidence,
        token_cost_usd=total_cost,
        model=deep_model,
    )
    await _persist(result, decision_id, market, repo)
    return result.model_dump(mode="json")


async def _persist(
    result: ResearchResult,
    decision_id: str,
    market: Market,
    repo: Repository,
) -> None:
    await repo.upsert_research(ResearchRecord(
        decision_id=decision_id,
        market_id=market.id,
        vertical=market.vertical.value,
        model=result.model,
        prior_fair_value=result.prior_fair_value,
        fair_value=result.fair_value,
        confidence=result.confidence,
        rationale=result.rationale,
        token_cost_usd=result.token_cost_usd,
        abstain=result.abstain,
    ))
    for attr in result.source_attributions:
        await repo.append_source_attribution(SourceAttributionRecord(
            decision_id=decision_id,
            source_name=attr.source_name,
            fair_value_delta=attr.fair_value_delta,
            note=attr.note,
        ))
    if result.abstain:
        await repo.append_trail_event(TrailEvent(
            decision_id=decision_id,
            market_id=market.id,
            agent="research",
            text=f"Abstained: confidence={result.confidence:.2f} < floor — SKIP",
            payload={"abstain": True, "confidence": result.confidence},
        ))


async def _worker_loop() -> None:
    repo = build_repository()
    await repo.init()
    mandate = _load_mandate()
    pid = os.getpid()
    log.info("research worker started (pid=%d)", pid)

    while True:
        task = await repo.claim_task("research", pid)
        if task is None:
            await asyncio.sleep(0.5)
            continue
        log.info("research: claimed task %s (decision=%s)", task.id, task.decision_id)
        try:
            output = await run_research(task, repo, mandate)
            await repo.complete_task(task.id, output)
            log.info("research: completed task %s fair_value=%.3f", task.id,
                     output.get("fair_value", 0))
        except Exception as e:
            log.exception("research: task %s failed", task.id)
            await repo.fail_task(task.id, str(e))


def main() -> None:
    from .._console import force_utf8
    force_utf8()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s [research] %(levelname)s %(message)s")
    asyncio.run(_worker_loop())


if __name__ == "__main__":
    main()
