"""Abstract Repository interface + all persistence record models.

Agents depend only on Repository — never on SqliteRepository or any DB detail.
Swap the backend by writing one new class that implements Repository.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Persistence record models ───────────────────────────────────────────────

class MarketRecord(BaseModel):
    market_id: str
    slug: str
    url: str
    question: str
    category: str = ""
    vertical: str = "other"
    yes_price: float
    no_price: float
    spread: float
    liquidity: float
    volume_24h: float
    end_date: datetime | None = None
    order_book_enabled: bool = True
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    flagged_reason: str = ""
    discovery_score: float = 0.0


class MarketSnapshot(BaseModel):
    market_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    yes_price: float
    no_price: float
    spread: float
    liquidity: float
    volume_24h: float


class DataSourceUseRecord(BaseModel):
    market_id: str
    decision_id: str
    source_name: str
    source_url: str = ""
    source_type: str = ""
    datapoints: dict[str, Any] = Field(default_factory=dict)
    acquisition_method: str = "free"
    cost_usd: float = 0.0
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    influenced_price: bool = False
    influenced_note: str = ""


class ResearchRecord(BaseModel):
    market_id: str
    decision_id: str
    vertical: str = ""
    model: str = ""
    prior_fair_value: float
    fair_value: float
    confidence: float
    rationale: str
    token_cost_usd: float = 0.0
    abstain: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SourceAttributionRecord(BaseModel):
    decision_id: str
    source_name: str
    fair_value_delta: float = 0.0
    note: str = ""


class RiskDecisionRecord(BaseModel):
    market_id: str
    decision_id: str
    market_price: float
    fair_value: float
    edge: float
    kelly_inputs: dict[str, Any] = Field(default_factory=dict)
    size_usd: float
    limit_price: float
    risk_checks: dict[str, Any] = Field(default_factory=dict)
    slippage_estimate: float = 0.0
    side: str = ""
    executed: bool = False
    reason: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FillRecord(BaseModel):
    market_id: str
    decision_id: str
    side: str
    size_usd: float
    avg_price: float
    tx_ref: str = ""
    paper: bool = True
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class OutcomeRecord(BaseModel):
    market_id: str
    decision_id: str
    resolved_value: float
    realized_pnl: float
    was_calibrated: bool = False
    recorded_at: datetime = Field(default_factory=datetime.utcnow)


class TrailEvent(BaseModel):
    """Every agent appends TrailEvents — the frontend renders these in order."""
    decision_id: str
    market_id: str
    agent: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    text: str                           # human-readable line shown to user
    payload: dict[str, Any] = Field(default_factory=dict)   # drill-down detail


class TaskRecord(BaseModel):
    """SQLite task-queue row — the IPC envelope between agent processes."""
    id: str
    task_type: str
    decision_id: str
    market_id: str = ""
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    worker_pid: int | None = None
    error: str = ""


# ── Abstract Repository ─────────────────────────────────────────────────────

class Repository(ABC):

    # ── Markets ──────────────────────────────────────────────────────────────
    @abstractmethod
    async def upsert_market(self, record: MarketRecord) -> None: ...

    @abstractmethod
    async def append_snapshot(self, snapshot: MarketSnapshot) -> None: ...

    @abstractmethod
    async def get_market(self, market_id: str) -> MarketRecord | None: ...

    # ── Decision trail ────────────────────────────────────────────────────────
    @abstractmethod
    async def append_trail_event(self, event: TrailEvent) -> None: ...

    @abstractmethod
    async def get_decision_trail(self, decision_id: str) -> list[TrailEvent]: ...

    # ── Research ──────────────────────────────────────────────────────────────
    @abstractmethod
    async def upsert_research(self, record: ResearchRecord) -> None: ...

    @abstractmethod
    async def append_source_attribution(self, record: SourceAttributionRecord) -> None: ...

    @abstractmethod
    async def append_data_source_use(self, record: DataSourceUseRecord) -> None: ...

    # ── Risk / execution ──────────────────────────────────────────────────────
    @abstractmethod
    async def upsert_risk_decision(self, record: RiskDecisionRecord) -> None: ...

    @abstractmethod
    async def append_fill(self, record: FillRecord) -> None: ...

    @abstractmethod
    async def append_outcome(self, record: OutcomeRecord) -> None: ...

    # ── Daily P&L (for circuit breaker) ──────────────────────────────────────
    @abstractmethod
    async def get_daily_loss(self, day: str) -> float: ...

    @abstractmethod
    async def add_daily_pnl(self, day: str, realised: float) -> None: ...

    # ── Task queue (SQLite IPC between agent processes) ───────────────────────
    @abstractmethod
    async def enqueue_task(self, task: TaskRecord) -> None: ...

    @abstractmethod
    async def claim_task(self, task_type: str, worker_pid: int) -> TaskRecord | None: ...

    @abstractmethod
    async def complete_task(self, task_id: str, output: dict[str, Any]) -> None: ...

    @abstractmethod
    async def fail_task(self, task_id: str, error: str) -> None: ...

    @abstractmethod
    async def get_task(self, task_id: str) -> TaskRecord | None: ...

    @abstractmethod
    async def get_market_history(self, market_id: str) -> list[MarketSnapshot]: ...

    # ── Read queries (for the read-only dashboard API) ────────────────────────
    @abstractmethod
    async def list_fills(self) -> list[FillRecord]: ...

    @abstractmethod
    async def list_outcomes(self) -> list[OutcomeRecord]: ...

    @abstractmethod
    async def get_fill_by_decision(self, decision_id: str) -> FillRecord | None: ...

    @abstractmethod
    async def get_outcome_by_decision(self, decision_id: str) -> OutcomeRecord | None: ...

    @abstractmethod
    async def get_research(self, decision_id: str) -> ResearchRecord | None: ...

    @abstractmethod
    async def get_risk_decision(self, decision_id: str) -> RiskDecisionRecord | None: ...

    @abstractmethod
    async def get_source_attributions(self, decision_id: str) -> list[SourceAttributionRecord]: ...

    @abstractmethod
    async def get_data_source_uses(self, decision_id: str) -> list[DataSourceUseRecord]: ...

    @abstractmethod
    async def get_latest_trail_timestamp(self) -> datetime | None: ...

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    @abstractmethod
    async def init(self) -> None:
        """Create tables / run migrations on first use."""
        ...
