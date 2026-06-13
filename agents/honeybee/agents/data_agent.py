"""Data Agent — maps a market topic to the data fetchers Research should run."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from ..venues.base import Market

log = logging.getLogger(__name__)


# Topic -> ordered fetcher names. Cheap defaults; paid feeds gated behind keys.
TOPIC_SOURCES: dict[str, list[str]] = {
    "sports.nba":    ["espn_scoreboard", "perplexity"],
    "sports.nfl":    ["espn_scoreboard", "perplexity"],
    "sports.epl":    ["perplexity"],
    "politics.us":   ["perplexity"],
    "crypto.price":  ["coingecko", "perplexity"],
    "macro":         ["perplexity"],
    "default":       ["perplexity"],
}


@dataclass
class ResearchPlan:
    market_id: str
    topic: str
    sources: list[str]
    context_snippets: list[str]  # raw text gathered from the sources


class DataAgent:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=15.0)

    def classify(self, m: Market) -> str:
        text = (m.question + " " + " ".join(m.tags)).lower()
        if any(k in text for k in ["nba", "lakers", "celtics", "warriors"]):
            return "sports.nba"
        if any(k in text for k in ["nfl", "super bowl", "patriots", "chiefs"]):
            return "sports.nfl"
        if any(k in text for k in ["premier league", "epl", "manchester", "arsenal"]):
            return "sports.epl"
        if any(k in text for k in ["bitcoin", "btc", "eth", "ethereum", "solana", "$"]):
            if any(k in text for k in ["price", "reach", "above", "below"]):
                return "crypto.price"
        if any(k in text for k in ["election", "president", "senator", "congress", "policy", "fed", "trump", "biden"]):
            return "politics.us"
        if any(k in text for k in ["gdp", "inflation", "cpi", "unemployment", "rates"]):
            return "macro"
        return "default"

    async def plan(self, m: Market) -> ResearchPlan:
        topic = self.classify(m)
        sources = TOPIC_SOURCES.get(topic, TOPIC_SOURCES["default"])
        snippets = await self._gather(m, sources)
        return ResearchPlan(
            market_id=m.market_id,
            topic=topic,
            sources=sources,
            context_snippets=snippets,
        )

    async def _gather(self, m: Market, sources: list[str]) -> list[str]:
        out: list[str] = []
        for src in sources:
            try:
                if src == "coingecko":
                    out.append(await self._coingecko(m))
                elif src == "espn_scoreboard":
                    out.append(await self._espn(m))
                # perplexity handled by Research agent (it's an LLM tool)
            except Exception as e:
                log.debug("data_agent source %s failed: %s", src, e)
        return [s for s in out if s]

    async def _coingecko(self, m: Market) -> str:
        sym_match = re.search(r"\b(bitcoin|btc|ethereum|eth|solana|sol)\b", m.question.lower())
        if not sym_match:
            return ""
        sym = sym_match.group(1)
        cg_id = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana"}.get(sym, sym)
        r = await self.http.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd", "include_24hr_change": "true"},
        )
        r.raise_for_status()
        data = r.json().get(cg_id, {})
        if not data:
            return ""
        return f"[coingecko] {cg_id} = ${data.get('usd')} (24h: {data.get('usd_24h_change', 0):+.2f}%)"

    async def _espn(self, m: Market) -> str:
        # ESPN's public scoreboard is league-dependent; we keep it generic.
        return ""  # placeholder; expand once we wire team-specific lookups
