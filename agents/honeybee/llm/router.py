"""LLM Router — cheap triage, escalate strong, mock fallback.

Routing policy:
  1. Run cheap model on `triage_prompt`. Costs ~$0.001.
  2. If `worth_deep_analysis=true` AND we're under the per-loop budget,
     run strong model on `deep_prompt`. Costs ~$0.01.
  3. Otherwise emit the triage result with downgraded confidence.

If no LLM keys are configured, the router returns a deterministic mock
response so the full pipeline still runs end-to-end (great for hackathon
demos and CI).
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import dataclass
from typing import Any

from ..config import CONFIG

log = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    text: str
    model: str
    cost_usd: float
    raw: dict[str, Any] | None = None


class LLMRouter:
    """Routes between cheap and strong models, with a mock fallback."""

    def __init__(self) -> None:
        self._anthropic = None
        self._openai = None
        self._spent_this_loop = 0.0
        self._init_clients()

    def _init_clients(self) -> None:
        if CONFIG.has_anthropic:
            try:
                from anthropic import AsyncAnthropic
                kwargs: dict[str, Any] = {"api_key": CONFIG.anthropic_api_key}
                if CONFIG.anthropic_base_url:
                    kwargs["base_url"] = CONFIG.anthropic_base_url
                self._anthropic = AsyncAnthropic(**kwargs)
                log.info("anthropic client → %s", CONFIG.anthropic_base_url or "api.anthropic.com (default)")
            except Exception as e:
                log.warning("anthropic client init failed: %s", e)
        if CONFIG.has_openai:
            try:
                from openai import AsyncOpenAI
                kwargs: dict[str, Any] = {"api_key": CONFIG.openai_api_key}
                if CONFIG.openai_base_url:
                    kwargs["base_url"] = CONFIG.openai_base_url
                self._openai = AsyncOpenAI(**kwargs)
                log.info("openai client → %s", CONFIG.openai_base_url or "api.openai.com (default)")
            except Exception as e:
                log.warning("openai client init failed: %s", e)

    def reset_loop_budget(self) -> None:
        self._spent_this_loop = 0.0

    @property
    def spent_this_loop(self) -> float:
        return self._spent_this_loop

    def _can_spend(self, est_cost: float) -> bool:
        return (self._spent_this_loop + est_cost) <= CONFIG.max_usd_per_loop

    async def cheap(self, system: str, user: str, *, max_tokens: int = 300) -> LLMResponse:
        # Prefer Anthropic Haiku for cheap tier when available; fall back to
        # OpenAI gpt-4o-mini; fall back to mock.
        if self._anthropic and self._can_spend(0.001):
            return await self._call_anthropic(system, user, "claude-haiku-4-5", max_tokens)
        if self._openai and self._can_spend(0.001):
            return await self._call_openai(system, user, CONFIG.llm_cheap_model, max_tokens)
        return self._mock(system, user, model="mock-cheap")

    async def strong(self, system: str, user: str, *, max_tokens: int = 800) -> LLMResponse:
        if not self._can_spend(0.01):
            log.info("loop budget exhausted, downgrading strong→cheap")
            return await self.cheap(system, user, max_tokens=max_tokens)
        if self._anthropic:
            return await self._call_anthropic(system, user, CONFIG.llm_strong_model, max_tokens)
        if self._openai:
            return await self._call_openai(system, user, "gpt-4o", max_tokens)
        return self._mock(system, user, model="mock-strong")

    async def _call_openai(self, system: str, user: str, model: str, max_tokens: int) -> LLMResponse:
        assert self._openai is not None
        resp = await self._openai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        text = resp.choices[0].message.content or ""
        # Rough cost estimate; tune per model. gpt-4o-mini ~$0.15/1M in, $0.60/1M out.
        in_tok = resp.usage.prompt_tokens if resp.usage else 0
        out_tok = resp.usage.completion_tokens if resp.usage else 0
        cost = (in_tok * 0.00000015) + (out_tok * 0.0000006)
        self._spent_this_loop += cost
        return LLMResponse(text=text, model=model, cost_usd=cost, raw={"usage": resp.usage.model_dump() if resp.usage else None})

    async def _call_anthropic(self, system: str, user: str, model: str, max_tokens: int) -> LLMResponse:
        assert self._anthropic is not None
        resp = await self._anthropic.messages.create(
            model=model,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        # claude sonnet 4.5 ~$3/1M in, $15/1M out; haiku ~$1/1M, $5/1M.
        if "haiku" in model:
            cost = (in_tok * 0.000001) + (out_tok * 0.000005)
        else:
            cost = (in_tok * 0.000003) + (out_tok * 0.000015)
        self._spent_this_loop += cost
        return LLMResponse(text=text, model=model, cost_usd=cost)

    def _mock(self, system: str, user: str, *, model: str) -> LLMResponse:
        """Deterministic mock — produces plausible JSON so downstream parsing works.

        Hash the input so the same market always yields the same answer.
        """
        h = hashlib.sha256((system + user).encode()).hexdigest()
        rng = random.Random(int(h[:8], 16))
        # Sniff which prompt we're answering so we return the right shape.
        if "triage" in user.lower() or "triage" in system.lower():
            payload = {
                "worth_deep_analysis": rng.random() < 0.3,
                "quick_fair_price": round(rng.uniform(0.2, 0.8), 3),
                "rationale": "[mock] heuristic triage based on stated odds",
            }
        else:
            payload = {
                "fair_prices": {"YES": round(rng.uniform(0.15, 0.85), 3)},
                "confidence": round(rng.uniform(0.45, 0.75), 3),
                "rationale": "[mock] no LLM key configured; deterministic stub",
                "sources": [],
            }
            payload["fair_prices"]["NO"] = round(1 - payload["fair_prices"]["YES"], 3)
        return LLMResponse(text=json.dumps(payload), model=model, cost_usd=0.0)
