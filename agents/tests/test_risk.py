from datetime import datetime, timezone

import pytest

from honeybee.agents.research import ResearchSignal
from honeybee.agents.risk import RiskAgent
from honeybee.ledger import Ledger
from honeybee.venues.base import Market


@pytest.fixture
async def ledger(tmp_path):
    l = Ledger(path=str(tmp_path / "test.db"))
    await l.init()
    return l


def _market(yes=0.30, no=0.70, liquidity=10_000, volume=500):
    return Market(
        venue="polymarket",
        market_id="M1",
        question="Will X happen?",
        outcomes=["YES", "NO"],
        prices={"YES": yes, "NO": no},
        volume_24h=volume,
        liquidity=liquidity,
        close_time=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_size_skips_below_confidence(ledger):
    risk = RiskAgent(ledger)
    sig = ResearchSignal("M1", {"YES": 0.50, "NO": 0.50}, confidence=0.30,
                         rationale="", sources=[], cost_usd=0, deep=False)
    out = await risk.size(_market(), sig)
    assert out.order is None and "confidence" in (out.rejected_reason or "")


@pytest.mark.asyncio
async def test_size_produces_order_with_edge(ledger):
    risk = RiskAgent(ledger)
    sig = ResearchSignal("M1", {"YES": 0.60, "NO": 0.40}, confidence=0.80,
                         rationale="", sources=[], cost_usd=0, deep=True)
    out = await risk.size(_market(yes=0.30, no=0.70), sig)
    assert out.order is not None
    assert out.order.outcome == "YES"
    assert out.order.size_usd > 0
    assert out.order.size_usd <= 25  # default per-market cap


@pytest.mark.asyncio
async def test_size_skips_no_edge(ledger):
    risk = RiskAgent(ledger)
    sig = ResearchSignal("M1", {"YES": 0.31, "NO": 0.69}, confidence=0.80,
                         rationale="", sources=[], cost_usd=0, deep=True)
    out = await risk.size(_market(yes=0.30, no=0.70), sig)
    assert out.order is None
