"""SqliteRepository — the swappable [PLACEHOLDER] backend.

Swap for Postgres by implementing Repository with a new class; agents never
import this module directly, only the Repository interface.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .repository import (
    DataSourceUseRecord,
    FillRecord,
    MarketRecord,
    MarketSnapshot,
    OutcomeRecord,
    Repository,
    ResearchRecord,
    RiskDecisionRecord,
    SourceAttributionRecord,
    TaskRecord,
    TrailEvent,
)

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS markets (
    market_id           TEXT PRIMARY KEY,
    slug                TEXT,
    url                 TEXT,
    question            TEXT,
    category            TEXT,
    vertical            TEXT,
    yes_price           REAL,
    no_price            REAL,
    spread              REAL,
    liquidity           REAL,
    volume_24h          REAL,
    end_date            TEXT,
    order_book_enabled  INTEGER DEFAULT 1,
    discovered_at       TEXT,
    flagged_reason      TEXT,
    discovery_score     REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id   TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    yes_price   REAL,
    no_price    REAL,
    spread      REAL,
    liquidity   REAL,
    volume_24h  REAL
);
CREATE INDEX IF NOT EXISTS idx_snap_market ON market_snapshots(market_id);

CREATE TABLE IF NOT EXISTS trail_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    market_id   TEXT NOT NULL,
    agent       TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    text        TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_trail_decision ON trail_events(decision_id);
CREATE INDEX IF NOT EXISTS idx_trail_market   ON trail_events(market_id);

CREATE TABLE IF NOT EXISTS research_records (
    decision_id         TEXT PRIMARY KEY,
    market_id           TEXT NOT NULL,
    vertical            TEXT,
    model               TEXT,
    prior_fair_value    REAL,
    fair_value          REAL,
    confidence          REAL,
    rationale           TEXT,
    token_cost_usd      REAL DEFAULT 0,
    abstain             INTEGER DEFAULT 0,
    created_at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_research_market ON research_records(market_id);

CREATE TABLE IF NOT EXISTS source_attributions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     TEXT NOT NULL,
    source_name     TEXT NOT NULL,
    fair_value_delta REAL DEFAULT 0,
    note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_attr_decision ON source_attributions(decision_id);

CREATE TABLE IF NOT EXISTS data_source_uses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id           TEXT NOT NULL,
    decision_id         TEXT NOT NULL,
    source_name         TEXT NOT NULL,
    source_url          TEXT,
    source_type         TEXT,
    datapoints          TEXT DEFAULT '{}',
    acquisition_method  TEXT DEFAULT 'free',
    cost_usd            REAL DEFAULT 0,
    fetched_at          TEXT,
    influenced_price    INTEGER DEFAULT 0,
    influenced_note     TEXT
);
CREATE INDEX IF NOT EXISTS idx_dsu_decision ON data_source_uses(decision_id);

CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id         TEXT PRIMARY KEY,
    market_id           TEXT NOT NULL,
    market_price        REAL,
    fair_value          REAL,
    edge                REAL,
    kelly_inputs        TEXT DEFAULT '{}',
    size_usd            REAL,
    limit_price         REAL,
    risk_checks         TEXT DEFAULT '{}',
    slippage_estimate   REAL DEFAULT 0,
    side                TEXT,
    executed            INTEGER DEFAULT 0,
    reason              TEXT,
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS fills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id   TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    side        TEXT,
    size_usd    REAL,
    avg_price   REAL,
    tx_ref      TEXT,
    paper       INTEGER DEFAULT 1,
    timestamp   TEXT
);
CREATE INDEX IF NOT EXISTS idx_fill_decision ON fills(decision_id);

CREATE TABLE IF NOT EXISTS outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id       TEXT NOT NULL,
    decision_id     TEXT NOT NULL,
    resolved_value  REAL,
    realized_pnl    REAL,
    was_calibrated  INTEGER DEFAULT 0,
    recorded_at     TEXT
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    day         TEXT PRIMARY KEY,
    realised    REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    task_type       TEXT NOT NULL,
    decision_id     TEXT NOT NULL,
    market_id       TEXT DEFAULT '',
    input_payload   TEXT NOT NULL DEFAULT '{}',
    output_payload  TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    claimed_at      TEXT,
    completed_at    TEXT,
    worker_pid      INTEGER,
    error           TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tasks_type_status ON tasks(task_type, status);
CREATE INDEX IF NOT EXISTS idx_tasks_decision    ON tasks(decision_id);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class SqliteRepository(Repository):
    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.getenv("LEDGER_PATH", "./var/honeybee.db")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    # ── Markets ───────────────────────────────────────────────────────────────

    async def upsert_market(self, r: MarketRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO markets
                  (market_id,slug,url,question,category,vertical,yes_price,no_price,
                   spread,liquidity,volume_24h,end_date,order_book_enabled,
                   discovered_at,flagged_reason,discovery_score)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(market_id) DO UPDATE SET
                  yes_price=excluded.yes_price, no_price=excluded.no_price,
                  spread=excluded.spread, liquidity=excluded.liquidity,
                  volume_24h=excluded.volume_24h, discovery_score=excluded.discovery_score
            """, (r.market_id, r.slug, r.url, r.question, r.category, r.vertical,
                  r.yes_price, r.no_price, r.spread, r.liquidity, r.volume_24h,
                  _iso(r.end_date), int(r.order_book_enabled),
                  _iso(r.discovered_at), r.flagged_reason, r.discovery_score))
            await db.commit()

    async def append_snapshot(self, s: MarketSnapshot) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO market_snapshots
                  (market_id,timestamp,yes_price,no_price,spread,liquidity,volume_24h)
                VALUES (?,?,?,?,?,?,?)
            """, (s.market_id, _iso(s.timestamp), s.yes_price, s.no_price,
                  s.spread, s.liquidity, s.volume_24h))
            await db.commit()

    async def get_market(self, market_id: str) -> MarketRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM markets WHERE market_id=?", (market_id,)) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["end_date"] = _dt(d.get("end_date"))
        d["discovered_at"] = _dt(d.get("discovered_at")) or datetime.utcnow()
        d["order_book_enabled"] = bool(d.get("order_book_enabled", 1))
        return MarketRecord(**d)

    async def get_market_history(self, market_id: str) -> list[MarketSnapshot]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM market_snapshots WHERE market_id=? ORDER BY timestamp",
                (market_id,),
            ) as cur:
                rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["timestamp"] = _dt(d["timestamp"]) or datetime.utcnow()
            out.append(MarketSnapshot(**d))
        return out

    # ── Trail ─────────────────────────────────────────────────────────────────

    async def append_trail_event(self, e: TrailEvent) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO trail_events (decision_id,market_id,agent,timestamp,text,payload)
                VALUES (?,?,?,?,?,?)
            """, (e.decision_id, e.market_id, e.agent, _iso(e.timestamp),
                  e.text, json.dumps(e.payload)))
            await db.commit()

    async def get_decision_trail(self, decision_id: str) -> list[TrailEvent]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM trail_events WHERE decision_id=? ORDER BY timestamp",
                (decision_id,),
            ) as cur:
                rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["timestamp"] = _dt(d["timestamp"]) or datetime.utcnow()
            d["payload"] = json.loads(d.get("payload") or "{}")
            out.append(TrailEvent(**d))
        return out

    # ── Research ──────────────────────────────────────────────────────────────

    async def upsert_research(self, r: ResearchRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO research_records
                  (decision_id,market_id,vertical,model,prior_fair_value,fair_value,
                   confidence,rationale,token_cost_usd,abstain,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(decision_id) DO UPDATE SET
                  fair_value=excluded.fair_value,
                  confidence=excluded.confidence,
                  rationale=excluded.rationale
            """, (r.decision_id, r.market_id, r.vertical, r.model,
                  r.prior_fair_value, r.fair_value, r.confidence, r.rationale,
                  r.token_cost_usd, int(r.abstain), _iso(r.created_at)))
            await db.commit()

    async def append_source_attribution(self, r: SourceAttributionRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO source_attributions (decision_id,source_name,fair_value_delta,note)
                VALUES (?,?,?,?)
            """, (r.decision_id, r.source_name, r.fair_value_delta, r.note))
            await db.commit()

    async def append_data_source_use(self, r: DataSourceUseRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO data_source_uses
                  (market_id,decision_id,source_name,source_url,source_type,datapoints,
                   acquisition_method,cost_usd,fetched_at,influenced_price,influenced_note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (r.market_id, r.decision_id, r.source_name, r.source_url,
                  r.source_type, json.dumps(r.datapoints), r.acquisition_method,
                  r.cost_usd, _iso(r.fetched_at), int(r.influenced_price), r.influenced_note))
            await db.commit()

    # ── Risk / execution ──────────────────────────────────────────────────────

    async def upsert_risk_decision(self, r: RiskDecisionRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO risk_decisions
                  (decision_id,market_id,market_price,fair_value,edge,kelly_inputs,
                   size_usd,limit_price,risk_checks,slippage_estimate,side,executed,reason,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(decision_id) DO UPDATE SET
                  executed=excluded.executed, reason=excluded.reason
            """, (r.decision_id, r.market_id, r.market_price, r.fair_value, r.edge,
                  json.dumps(r.kelly_inputs), r.size_usd, r.limit_price,
                  json.dumps(r.risk_checks), r.slippage_estimate, r.side,
                  int(r.executed), r.reason, _iso(r.created_at)))
            await db.commit()

    async def append_fill(self, r: FillRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO fills (market_id,decision_id,side,size_usd,avg_price,tx_ref,paper,timestamp)
                VALUES (?,?,?,?,?,?,?,?)
            """, (r.market_id, r.decision_id, r.side, r.size_usd, r.avg_price,
                  r.tx_ref, int(r.paper), _iso(r.timestamp)))
            await db.commit()

    async def append_outcome(self, r: OutcomeRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO outcomes
                  (market_id,decision_id,resolved_value,realized_pnl,was_calibrated,recorded_at)
                VALUES (?,?,?,?,?,?)
            """, (r.market_id, r.decision_id, r.resolved_value, r.realized_pnl,
                  int(r.was_calibrated), _iso(r.recorded_at)))
            await db.commit()

    # ── Daily P&L ─────────────────────────────────────────────────────────────

    async def get_daily_loss(self, day: str) -> float:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT realised FROM daily_pnl WHERE day=?", (day,)) as cur:
                row = await cur.fetchone()
        return float(row[0]) if row else 0.0

    async def add_daily_pnl(self, day: str, realised: float) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO daily_pnl (day, realised) VALUES (?,?)
                ON CONFLICT(day) DO UPDATE SET realised = realised + excluded.realised
            """, (day, realised))
            await db.commit()

    # ── Task queue ────────────────────────────────────────────────────────────

    async def enqueue_task(self, task: TaskRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO tasks
                  (id,task_type,decision_id,market_id,input_payload,output_payload,
                   status,created_at,error)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (task.id, task.task_type, task.decision_id, task.market_id,
                  json.dumps(task.input_payload), json.dumps(task.output_payload),
                  task.status, _iso(task.created_at), task.error))
            await db.commit()

    async def claim_task(self, task_type: str, worker_pid: int) -> TaskRecord | None:
        """Atomically claim one pending task. Returns None if nothing to do."""
        async with aiosqlite.connect(self.path) as db:
            # WAL mode + BEGIN IMMEDIATE gives us exclusive write access for the claim.
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute("""
                SELECT id FROM tasks
                WHERE task_type=? AND status='pending'
                ORDER BY created_at
                LIMIT 1
            """, (task_type,)) as cur:
                row = await cur.fetchone()
            if not row:
                await db.execute("ROLLBACK")
                return None
            task_id = row[0]
            now = datetime.utcnow().isoformat()
            await db.execute("""
                UPDATE tasks SET status='claimed', claimed_at=?, worker_pid=?
                WHERE id=?
            """, (now, worker_pid, task_id))
            await db.commit()

        return await self.get_task(task_id)

    async def complete_task(self, task_id: str, output: dict[str, Any]) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                UPDATE tasks SET status='done', output_payload=?, completed_at=?
                WHERE id=?
            """, (json.dumps(output), datetime.utcnow().isoformat(), task_id))
            await db.commit()

    async def fail_task(self, task_id: str, error: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                UPDATE tasks SET status='failed', error=?, completed_at=?
                WHERE id=?
            """, (error, datetime.utcnow().isoformat(), task_id))
            await db.commit()

    # ── Read queries (dashboard API) ──────────────────────────────────────────

    async def list_fills(self) -> list[FillRecord]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM fills ORDER BY timestamp") as cur:
                rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r); d.pop("id", None)
            d["paper"] = bool(d.get("paper", 1))
            d["timestamp"] = _dt(d.get("timestamp")) or datetime.utcnow()
            out.append(FillRecord(**d))
        return out

    async def list_outcomes(self) -> list[OutcomeRecord]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM outcomes ORDER BY recorded_at") as cur:
                rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r); d.pop("id", None)
            d["was_calibrated"] = bool(d.get("was_calibrated", 0))
            d["recorded_at"] = _dt(d.get("recorded_at")) or datetime.utcnow()
            out.append(OutcomeRecord(**d))
        return out

    async def get_fill_by_decision(self, decision_id: str) -> FillRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM fills WHERE decision_id=? ORDER BY timestamp DESC LIMIT 1",
                (decision_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        d = dict(row); d.pop("id", None)
        d["paper"] = bool(d.get("paper", 1))
        d["timestamp"] = _dt(d.get("timestamp")) or datetime.utcnow()
        return FillRecord(**d)

    async def get_outcome_by_decision(self, decision_id: str) -> OutcomeRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM outcomes WHERE decision_id=? ORDER BY recorded_at DESC LIMIT 1",
                (decision_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        d = dict(row); d.pop("id", None)
        d["was_calibrated"] = bool(d.get("was_calibrated", 0))
        d["recorded_at"] = _dt(d.get("recorded_at")) or datetime.utcnow()
        return OutcomeRecord(**d)

    async def get_research(self, decision_id: str) -> ResearchRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM research_records WHERE decision_id=?", (decision_id,)
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["abstain"] = bool(d.get("abstain", 0))
        d["created_at"] = _dt(d.get("created_at")) or datetime.utcnow()
        return ResearchRecord(**d)

    async def get_risk_decision(self, decision_id: str) -> RiskDecisionRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM risk_decisions WHERE decision_id=?", (decision_id,)
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["kelly_inputs"] = json.loads(d.get("kelly_inputs") or "{}")
        d["risk_checks"] = json.loads(d.get("risk_checks") or "{}")
        d["executed"] = bool(d.get("executed", 0))
        d["created_at"] = _dt(d.get("created_at")) or datetime.utcnow()
        return RiskDecisionRecord(**d)

    async def get_source_attributions(self, decision_id: str) -> list[SourceAttributionRecord]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM source_attributions WHERE decision_id=?", (decision_id,)
            ) as cur:
                rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r); d.pop("id", None)
            out.append(SourceAttributionRecord(**d))
        return out

    async def get_data_source_uses(self, decision_id: str) -> list[DataSourceUseRecord]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM data_source_uses WHERE decision_id=?", (decision_id,)
            ) as cur:
                rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r); d.pop("id", None)
            d["datapoints"] = json.loads(d.get("datapoints") or "{}")
            d["influenced_price"] = bool(d.get("influenced_price", 0))
            d["fetched_at"] = _dt(d.get("fetched_at")) or datetime.utcnow()
            out.append(DataSourceUseRecord(**d))
        return out

    async def get_latest_trail_timestamp(self) -> datetime | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT timestamp FROM trail_events ORDER BY timestamp DESC LIMIT 1"
            ) as cur:
                row = await cur.fetchone()
        return _dt(row[0]) if row else None

    async def get_task(self, task_id: str) -> TaskRecord | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["input_payload"] = json.loads(d.get("input_payload") or "{}")
        d["output_payload"] = json.loads(d.get("output_payload") or "{}")
        for f in ("created_at", "claimed_at", "completed_at"):
            d[f] = _dt(d.get(f))
        return TaskRecord(**d)
