"""Inter-agent data contracts — all agents communicate only through these models."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────

class Vertical(str, Enum):
    sports = "sports"
    politics = "politics"
    macro = "macro"
    weather = "weather"
    other = "other"


class TradeSide(str, Enum):
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"
    SKIP = "SKIP"


class TaskStatus(str, Enum):
    pending = "pending"
    claimed = "claimed"
    done = "done"
    failed = "failed"


class TaskType(str, Enum):
    discover = "discover"
    research = "research"
    fetch_data = "fetch_data"
    execute = "execute"
    arbitrage = "arbitrage"


# ── Core market model ───────────────────────────────────────────────────────

class Market(BaseModel):
    id: str
    slug: str
    url: str
    question: str
    category: str = ""
    vertical: Vertical = Vertical.other
    yes_price: float
    no_price: float
    spread: float
    liquidity: float
    volume_24h: float
    end_date: datetime | None = None
    order_book_enabled: bool = True


# ── Data Agent ──────────────────────────────────────────────────────────────

class DataSourceUse(BaseModel):
    source_name: str
    source_url: str = ""
    source_type: str = ""                # free | search_api | x402_paid
    datapoints: dict[str, Any] = Field(default_factory=dict)
    acquisition_method: str = "free"
    cost_usd: float = 0.0
    influenced_price: bool = False
    influenced_note: str = ""


class DataBundle(BaseModel):
    market_id: str
    sources: list[DataSourceUse] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


# ── Research Agent ──────────────────────────────────────────────────────────

class SourceAttribution(BaseModel):
    source_name: str
    fair_value_delta: float = 0.0
    note: str = ""


class ResearchResult(BaseModel):
    market_id: str
    prior_fair_value: float
    fair_value: float
    confidence: float
    rationale: str
    source_attributions: list[SourceAttribution] = Field(default_factory=list)
    abstain: bool = False
    token_cost_usd: float = 0.0
    model: str = ""


# ── Execution & Risk Agent ──────────────────────────────────────────────────

class TradeDecision(BaseModel):
    market_id: str
    side: TradeSide
    size_usd: float = 0.0
    limit_price: float = 0.0
    edge: float = 0.0
    expected_value: float = 0.0
    reason: str = ""


class Fill(BaseModel):
    market_id: str
    side: TradeSide
    size_usd: float
    avg_price: float
    tx_ref: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    paper: bool = True


class Outcome(BaseModel):
    market_id: str
    resolved_value: float           # 1.0 = YES resolved, 0.0 = NO resolved
    realized_pnl: float
    was_calibrated: bool = False


# ── SQLite task-queue envelope ──────────────────────────────────────────────
# Every inter-process message travels as an AgentTask row in the DB.

class AgentTask(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    task_type: TaskType
    decision_id: str
    market_id: str = ""
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.pending
    created_at: datetime = Field(default_factory=datetime.utcnow)
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    worker_pid: int | None = None
    error: str = ""
