"""Lightweight crash-safe state ledger backed by SQLite.

Every meaningful state transition (market discovered, signal produced,
order submitted, fill received, market resolved) is journalled here so
the orchestrator can resume after a crash without double-submitting.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from .config import CONFIG


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL DEFAULT (strftime('%s','now')),
    kind        TEXT NOT NULL,
    market_id   TEXT,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_market ON events(market_id);
CREATE INDEX IF NOT EXISTS idx_events_kind   ON events(kind);

CREATE TABLE IF NOT EXISTS submitted_orders (
    idempotency_key TEXT PRIMARY KEY,
    ts              REAL NOT NULL DEFAULT (strftime('%s','now')),
    payload         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    day        TEXT PRIMARY KEY,
    realised   REAL NOT NULL DEFAULT 0,
    notional   REAL NOT NULL DEFAULT 0
);

-- v2: user-centric research-as-a-service tables

CREATE TABLE IF NOT EXISTS users (
    address          TEXT PRIMARY KEY,
    ens              TEXT,
    created_at       REAL NOT NULL DEFAULT (strftime('%s','now')),
    broker_creds     TEXT                       -- encrypted blob (optional, never plaintext)
);

-- Recommendations the agent produced after a paid research call.
CREATE TABLE IF NOT EXISTS recommendations (
    rec_id                       TEXT PRIMARY KEY,
    ts                           REAL NOT NULL DEFAULT (strftime('%s','now')),
    agent_ens                    TEXT NOT NULL,
    user_address                 TEXT NOT NULL,
    venue                        TEXT NOT NULL,
    market_id                    TEXT NOT NULL,
    market_question              TEXT NOT NULL,
    outcome                      TEXT NOT NULL,
    side                         TEXT NOT NULL,
    fair_price                   REAL NOT NULL,
    market_price                 REAL NOT NULL,
    edge                         REAL NOT NULL,
    confidence                   REAL NOT NULL,
    suggested_size_usd           REAL NOT NULL,
    rationale                    TEXT NOT NULL,
    sources                      TEXT NOT NULL DEFAULT '[]',
    research_hash                TEXT NOT NULL,
    research_attestation_tx      TEXT,
    expires_at                   REAL NOT NULL,
    status                       TEXT NOT NULL DEFAULT 'pending'  -- pending | approved | rejected | expired | executed | failed
);
CREATE INDEX IF NOT EXISTS idx_rec_user   ON recommendations(user_address);
CREATE INDEX IF NOT EXISTS idx_rec_agent  ON recommendations(agent_ens);
CREATE INDEX IF NOT EXISTS idx_rec_status ON recommendations(status);

-- Reusable research blobs keyed by deterministic hash.
CREATE TABLE IF NOT EXISTS research_cache (
    research_hash    TEXT PRIMARY KEY,
    ts               REAL NOT NULL DEFAULT (strftime('%s','now')),
    agent_ens        TEXT NOT NULL,
    market_id        TEXT NOT NULL,
    payload          TEXT NOT NULL,             -- full Recommendation body (JSON)
    cost_usd         REAL NOT NULL,
    attestation_tx   TEXT
);
CREATE INDEX IF NOT EXISTS idx_cache_market ON research_cache(market_id);

-- Mirror of on-chain attestations we've written or observed (denormalised for fast UI).
CREATE TABLE IF NOT EXISTS attestations (
    tx_hash          TEXT PRIMARY KEY,
    ts               REAL NOT NULL DEFAULT (strftime('%s','now')),
    kind             TEXT NOT NULL,             -- research | trade | resolution
    agent_ens        TEXT,
    user_address     TEXT,
    market_id        TEXT,
    payload          TEXT NOT NULL,
    block_number     INTEGER,
    chain_id         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_attest_agent  ON attestations(agent_ens);
CREATE INDEX IF NOT EXISTS idx_attest_market ON attestations(market_id);
CREATE INDEX IF NOT EXISTS idx_attest_kind   ON attestations(kind);

-- Payments (user → agent, agent → agent via x402).
CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL DEFAULT (strftime('%s','now')),
    agent_ens       TEXT NOT NULL,
    from_address    TEXT NOT NULL,
    amount_usd      REAL NOT NULL,
    tx_hash         TEXT,
    kind            TEXT NOT NULL DEFAULT 'fund' -- fund | hire | x402 | refund
);
CREATE INDEX IF NOT EXISTS idx_pay_agent ON payments(agent_ens);
"""


class Ledger:
    def __init__(self, path: str = CONFIG.ledger_path) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def record(self, kind: str, payload: dict[str, Any], market_id: str | None = None) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO events (kind, market_id, payload) VALUES (?, ?, ?)",
                (kind, market_id, json.dumps(payload, default=str)),
            )
            await db.commit()

    async def already_submitted(self, idempotency_key: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT 1 FROM submitted_orders WHERE idempotency_key = ?",
                (idempotency_key,),
            ) as cur:
                return await cur.fetchone() is not None

    async def mark_submitted(self, idempotency_key: str, payload: dict[str, Any]) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO submitted_orders (idempotency_key, payload) VALUES (?, ?)",
                (idempotency_key, json.dumps(payload, default=str)),
            )
            await db.commit()

    async def add_pnl(self, day: str, realised: float, notional: float) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO daily_pnl (day, realised, notional)
                VALUES (?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                    realised = realised + excluded.realised,
                    notional = notional + excluded.notional
                """,
                (day, realised, notional),
            )
            await db.commit()

    async def get_daily_loss(self, day: str) -> float:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT realised FROM daily_pnl WHERE day = ?", (day,)
            ) as cur:
                row = await cur.fetchone()
                return float(row[0]) if row else 0.0

    # ───────── v2: recommendations ───────────────────────────────────────
    async def save_recommendation(self, rec: dict[str, Any]) -> None:
        cols = ("rec_id", "agent_ens", "user_address", "venue", "market_id",
                "market_question", "outcome", "side", "fair_price", "market_price",
                "edge", "confidence", "suggested_size_usd", "rationale", "sources",
                "research_hash", "research_attestation_tx", "expires_at", "status")
        vals = [rec.get(c) if c != "sources" else json.dumps(rec.get(c) or [])
                for c in cols]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                f"INSERT OR REPLACE INTO recommendations ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})",
                vals,
            )
            await db.commit()

    async def get_recommendation(self, rec_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM recommendations WHERE rec_id = ?", (rec_id,)
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["sources"] = json.loads(d.get("sources") or "[]")
        return d

    async def list_recommendations(
        self, *, user_address: str | None = None, agent_ens: str | None = None,
        status: str | None = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM recommendations WHERE 1=1"
        args: list = []
        if user_address:
            sql += " AND user_address = ?"; args.append(user_address)
        if agent_ens:
            sql += " AND agent_ens = ?"; args.append(agent_ens)
        if status:
            sql += " AND status = ?"; args.append(status)
        sql += " ORDER BY ts DESC LIMIT ?"; args.append(limit)
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, args) as cur:
                rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r); d["sources"] = json.loads(d.get("sources") or "[]"); out.append(d)
        return out

    async def update_recommendation_status(self, rec_id: str, status: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE recommendations SET status = ? WHERE rec_id = ?", (status, rec_id),
            )
            await db.commit()

    # ───────── v2: research cache ────────────────────────────────────────
    async def cache_research(self, research_hash: str, agent_ens: str, market_id: str,
                             payload: dict[str, Any], cost_usd: float,
                             attestation_tx: str | None = None) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO research_cache
                   (research_hash, agent_ens, market_id, payload, cost_usd, attestation_tx)
                   VALUES (?,?,?,?,?,?)""",
                (research_hash, agent_ens, market_id,
                 json.dumps(payload, default=str), cost_usd, attestation_tx),
            )
            await db.commit()

    async def lookup_research(self, research_hash: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM research_cache WHERE research_hash = ?", (research_hash,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        d = dict(row); d["payload"] = json.loads(d["payload"]); return d

    # ───────── v2: attestations mirror ───────────────────────────────────
    async def save_attestation(self, kind: str, tx_hash: str, payload: dict[str, Any],
                               *, agent_ens: str | None = None,
                               user_address: str | None = None,
                               market_id: str | None = None,
                               block_number: int | None = None,
                               chain_id: int = 0) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO attestations
                   (tx_hash, kind, agent_ens, user_address, market_id,
                    payload, block_number, chain_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (tx_hash, kind, agent_ens, user_address, market_id,
                 json.dumps(payload, default=str), block_number, chain_id),
            )
            await db.commit()

    async def list_attestations(self, *, agent_ens: str | None = None,
                                kind: str | None = None, limit: int = 50,
                                ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM attestations WHERE 1=1"
        args: list = []
        if agent_ens: sql += " AND agent_ens=?"; args.append(agent_ens)
        if kind:      sql += " AND kind=?";      args.append(kind)
        sql += " ORDER BY ts DESC LIMIT ?";     args.append(limit)
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, args) as cur:
                rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r); d["payload"] = json.loads(d["payload"]); out.append(d)
        return out
