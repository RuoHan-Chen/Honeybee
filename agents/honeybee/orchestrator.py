"""Honeybee Orchestrator — the master async loop.

Wires Discovery → Data → Research → Risk → Execution and journals every
transition to the SQLite ledger so crashes don't double-trade.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import asdict

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .agents.data_agent import DataAgent
from .agents.discovery import DiscoveryAgent
from .agents.execution import ExecutionAgent
from .agents.recommender import build_recommendation
from .agents.research import ResearchAgent
from .agents.risk import RiskAgent
from .config import CONFIG
from .ledger import Ledger
from .llm.router import LLMRouter
from .skills import ALL_SKILLS
from .venues import GeminiAdapter, KalshiAdapter, PolymarketAdapter

# House agent ENS used by the background discovery loop. Per-user paid runs
# use the agent's own configured ENS instead.
HOUSE_AGENT_ENS = "house.honeybee.agent.eth"

console = Console()


def _setup_logging() -> None:
    logging.basicConfig(
        level=CONFIG.log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


class Orchestrator:
    def __init__(self) -> None:
        self.ledger = Ledger()
        self.llm = LLMRouter()
        self.venues = [PolymarketAdapter(), KalshiAdapter(), GeminiAdapter()]
        self.discovery = DiscoveryAgent(
            self.venues,
            max_book_fetches=CONFIG.discovery_max_book_fetches,
        )
        self.data_agent = DataAgent()
        self.research = ResearchAgent(self.llm)
        self.risk = RiskAgent(self.ledger)
        self.execution = ExecutionAgent(self.ledger)

        # Pluggable skill prompts — keyed by topic prefix.
        self.skill_prompts: dict[str, str] = {}
        for skill in ALL_SKILLS:
            skill.register(self)

        self._stop = asyncio.Event()

    def shutdown(self, *_: object) -> None:
        console.print("[yellow]Shutting down…[/yellow]")
        self._stop.set()

    async def run(self) -> None:
        await self.ledger.init()
        self._banner()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.shutdown)
            except NotImplementedError:
                pass  # Windows

        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception as e:
                logging.exception("orchestrator tick failed: %s", e)
            await self._sleep(CONFIG.loop_interval_sec)

    async def _sleep(self, seconds: int) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _banner(self) -> None:
        mode = "[green]PAPER[/green]" if CONFIG.dry_run else "[bold red]LIVE[/bold red]"
        console.rule(f"[bold yellow]🐝 Honeybee[/bold yellow]  mode={mode}")
        console.print(f"  bankroll: ${CONFIG.bankroll_usd:,.2f}   "
                      f"per-loop LLM cap: ${CONFIG.max_usd_per_loop:.2f}   "
                      f"daily loss limit: ${CONFIG.daily_loss_limit_usd:,.2f}")
        llm_state = []
        if CONFIG.has_anthropic: llm_state.append("anthropic")
        if CONFIG.has_openai:    llm_state.append("openai")
        if CONFIG.has_perplexity: llm_state.append("perplexity")
        console.print(f"  LLMs: {', '.join(llm_state) or '[dim]mock-only (no keys)[/dim]'}")
        console.print()

    async def tick(self) -> None:
        self.llm.reset_loop_budget()

        scored = await self.discovery.scan(top_n=CONFIG.discovery_top_n)
        await self.ledger.record("discovery_scan", {"count": len(scored)})
        # Snapshot top candidates for the UI.
        await self.ledger.record("discovery_snapshot", {
            "markets": [
                {
                    "venue": s.market.venue,
                    "market_id": s.market.market_id,
                    "question": s.market.question,
                    "prices": s.market.prices,
                    "volume_24h": s.market.volume_24h,
                    "uncertainty": s.market.uncertainty,
                    "score": s.score,
                    "url": s.market.url,
                }
                for s in scored
            ],
        })
        if not scored:
            console.print("[dim]no candidates this tick[/dim]")
            return

        table = Table(title=f"Top {len(scored)} long-tail candidates", show_lines=False)
        for col in ("venue", "market", "spread", "vol24h", "score"):
            table.add_column(col)
        for s in scored[:10]:
            table.add_row(
                s.market.venue,
                (s.market.question[:60] + "…") if len(s.market.question) > 60 else s.market.question,
                f"{s.market.spread:.3f}",
                f"${s.market.volume_24h:,.0f}",
                f"{s.score:.3f}",
            )
        console.print(table)

        # Background loop runs research and *caches* it. It does NOT execute.
        # User-initiated paid runs (via the API) read from this cache when possible.
        cached = 0
        for s in scored:
            m = s.market
            try:
                rec = await self.research_market(
                    market=m, user_address="0xHouse", agent_ens=HOUSE_AGENT_ENS,
                )
                if rec is None:
                    continue
                cached += 1
                console.print(
                    f"  [cyan]→ research[/cyan] {m.venue} {rec['outcome']} "
                    f"fair={rec['fair_price']:.3f} mkt={rec['market_price']:.3f} "
                    f"edge={rec['edge']:+.3f} conf={rec['confidence']:.2f}  "
                    f"size=${rec['suggested_size_usd']:.2f}  "
                    f"cost=${rec.get('_cost_usd', 0):.4f}"
                )
            except Exception as e:
                logging.exception("market loop failed for %s: %s", m.market_id, e)

        console.print(
            f"[bold]tick complete[/bold] — research cached: {cached}   "
            f"LLM spend: ${self.llm.spent_this_loop:.4f}\n"
        )

    async def research_market(self, *, market, user_address: str,
                              agent_ens: str) -> dict | None:
        """Run the full research pipeline for one market and persist a Recommendation.

        Called by:
          - the background tick (with HOUSE_AGENT_ENS)
          - the /research API endpoint after a paid x402 settlement

        Returns the Recommendation dict, or None if Risk rejected.
        """
        plan = await self.data_agent.plan(market)
        await self.ledger.record("plan", asdict(plan), market_id=market.market_id)

        signal = await self.research.analyze(market, plan)
        await self.ledger.record("signal", asdict(signal), market_id=market.market_id)

        decision = await self.risk.size(market, signal)
        if decision.order is None:
            await self.ledger.record(
                "skipped",
                {"reason": decision.rejected_reason, "edge": decision.edge},
                market_id=market.market_id,
            )
            return None

        rec = build_recommendation(
            agent_ens=agent_ens, user_address=user_address,
            market=market, signal=signal, decision=decision,
        )
        # Stash full rec into research cache (keyed by hash → reusable by other agents).
        cached = await self.ledger.lookup_research(rec["research_hash"])
        if cached is None:
            await self.ledger.cache_research(
                research_hash=rec["research_hash"],
                agent_ens=agent_ens,
                market_id=market.market_id,
                payload=rec,
                cost_usd=signal.cost_usd,
            )

        await self.ledger.save_recommendation(rec)
        rec["_cost_usd"] = signal.cost_usd
        return rec


async def main() -> None:
    _setup_logging()
    await Orchestrator().run()


if __name__ == "__main__":
    asyncio.run(main())
