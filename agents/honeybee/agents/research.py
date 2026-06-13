"""Research Agent — LLM-driven probability estimation."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from ..config import CONFIG
from ..llm.router import LLMRouter
from ..venues.base import Market
from .data_agent import ResearchPlan

log = logging.getLogger(__name__)


@dataclass
class ResearchSignal:
    market_id: str
    fair_prices: dict[str, float]
    confidence: float
    rationale: str
    sources: list[str]
    cost_usd: float
    deep: bool


SYSTEM_TRIAGE = """You are a triage analyst for a prediction-market trading agent.
Given a market with current outcome prices, decide whether it merits deeper research.
Return ONLY a JSON object with keys:
  worth_deep_analysis (bool)
  quick_fair_price (float 0..1 for the YES/first outcome)
  rationale (one short sentence)
A market is "worth deep analysis" if there's plausibly >5% edge available."""

SYSTEM_DEEP = """You are a quantitative analyst for a long-tail prediction-market trading agent.
You will be given:
  - the market question and current outcome prices
  - structured context from data sources (sports stats, prices, news)
Output ONLY a JSON object:
  fair_prices: {outcome: probability}  (must sum to ~1.0)
  confidence: float 0..1                (how sure you are in those probabilities)
  rationale: 2-3 sentence explanation
  sources: list[string]                 (which evidence you actually used)
Be calibrated. If you have no real edge, return prices near current market and confidence < 0.55."""


class ResearchAgent:
    def __init__(self, llm: LLMRouter, http: httpx.AsyncClient | None = None) -> None:
        self.llm = llm
        self.http = http or httpx.AsyncClient(timeout=20.0)

    async def analyze(self, m: Market, plan: ResearchPlan) -> ResearchSignal:
        # 1. Triage with cheap model.
        triage_user = self._market_brief(m)
        triage = await self.llm.cheap(SYSTEM_TRIAGE, triage_user)
        triage_data = _safe_json(triage.text)

        total_cost = triage.cost_usd
        worth_deep = bool(triage_data.get("worth_deep_analysis", False))

        if not worth_deep:
            # Emit triage-quality signal with lowered confidence.
            quick = float(triage_data.get("quick_fair_price", 0.5))
            primary = m.outcomes[0] if m.outcomes else "YES"
            other = m.outcomes[1] if len(m.outcomes) > 1 else "NO"
            return ResearchSignal(
                market_id=m.market_id,
                fair_prices={primary: quick, other: round(1 - quick, 3)},
                confidence=0.40,
                rationale=triage_data.get("rationale", "triage-only"),
                sources=[],
                cost_usd=total_cost,
                deep=False,
            )

        # 2. Gather Perplexity context if configured.
        perplexity_snippet = await self._perplexity(m) if "perplexity" in plan.sources else ""
        all_context = list(plan.context_snippets) + ([perplexity_snippet] if perplexity_snippet else [])

        deep_user = self._market_brief(m) + "\n\nContext:\n" + ("\n".join(all_context) or "(no external context)")
        deep = await self.llm.strong(SYSTEM_DEEP, deep_user)
        deep_data = _safe_json(deep.text)
        total_cost += deep.cost_usd

        fair = deep_data.get("fair_prices") or {}
        # Normalise to outcomes we actually have.
        normalised = {o: float(fair.get(o, m.prices.get(o, 0.5))) for o in m.outcomes}
        s = sum(normalised.values()) or 1.0
        normalised = {k: round(v / s, 4) for k, v in normalised.items()}

        return ResearchSignal(
            market_id=m.market_id,
            fair_prices=normalised,
            confidence=float(deep_data.get("confidence", 0.5)),
            rationale=str(deep_data.get("rationale", "")),
            sources=list(deep_data.get("sources", [])),
            cost_usd=total_cost,
            deep=True,
        )

    def _market_brief(self, m: Market) -> str:
        prices_str = ", ".join(f"{o}={p:.3f}" for o, p in m.prices.items())
        close = m.close_time.isoformat() if m.close_time else "unknown"
        return (
            f"Venue: {m.venue}\n"
            f"Question: {m.question}\n"
            f"Outcomes / current prices: {prices_str}\n"
            f"24h volume: ${m.volume_24h:,.0f}\n"
            f"Closes: {close}\n"
            f"Tags: {', '.join(m.tags) or 'none'}"
        )

    async def _perplexity(self, m: Market) -> str:
        if not CONFIG.has_perplexity:
            return ""
        try:
            r = await self.http.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {CONFIG.perplexity_api_key}"},
                json={
                    "model": "sonar",
                    "messages": [{
                        "role": "user",
                        "content": (
                            f"Provide concise factual context (max 200 words) relevant to "
                            f"this prediction market question: {m.question!r}. "
                            f"Focus on recent developments and base rates."
                        ),
                    }],
                    "max_tokens": 300,
                },
                timeout=20.0,
            )
            r.raise_for_status()
            return "[perplexity] " + r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.debug("perplexity failed: %s", e)
            return ""


def _safe_json(text: str) -> dict:
    text = text.strip()
    # Strip ```json fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        # Try to find a JSON object inside the text.
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except Exception:
            log.debug("research: could not parse LLM JSON: %s", text[:200])
            return {}
