"""SupabaseRepository — the real Postgres backend, via Supabase PostgREST.

Implements the same Repository interface as SqliteRepository, so it's a drop-in
swap (set REPO_BACKEND=supabase). Talks to Supabase over PostgREST using httpx
and the service_role key (server-side only — never ship that key to the browser).

Run config/supabase_schema.sql once in the Supabase SQL Editor before using this.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx

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


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class SupabaseRepository(Repository):
    def __init__(self, url: str | None = None, key: str | None = None) -> None:
        base = (url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        if not base:
            raise EnvironmentError("SUPABASE_URL not set")
        # service_role for server-side full access; falls back to anon if absent.
        self.key = key or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
        if not self.key:
            raise EnvironmentError("SUPABASE_SERVICE_ROLE_KEY / SUPABASE_ANON_KEY not set")
        self.rest = f"{base}/rest/v1"
        self._headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        self.http = httpx.AsyncClient(timeout=30.0, headers=self._headers)

    async def init(self) -> None:
        # Schema is created via config/supabase_schema.sql in the SQL editor.
        # Verify connectivity + that a core table exists.
        r = await self.http.get(f"{self.rest}/markets", params={"limit": "1", "select": "market_id"})
        if r.status_code == 404:
            raise RuntimeError(
                "Supabase tables not found. Run config/supabase_schema.sql in the SQL Editor first."
            )
        r.raise_for_status()

    # ── low-level helpers ──────────────────────────────────────────────────────

    async def _insert(self, table: str, row: dict[str, Any], *, upsert: bool = False) -> None:
        headers = {"Prefer": "resolution=merge-duplicates"} if upsert else {"Prefer": "return=minimal"}
        r = await self.http.post(f"{self.rest}/{table}", json=row, headers=headers)
        r.raise_for_status()

    async def _select(self, table: str, params: dict[str, str]) -> list[dict]:
        r = await self.http.get(f"{self.rest}/{table}", params=params)
        r.raise_for_status()
        return r.json()

    async def _patch(self, table: str, filters: dict[str, str], row: dict[str, Any]) -> None:
        r = await self.http.patch(
            f"{self.rest}/{table}", params=filters, json=row,
            headers={"Prefer": "return=minimal"},
        )
        r.raise_for_status()

    # ── markets ─────────────────────────────────────────────────────────────────

    async def upsert_market(self, r: MarketRecord) -> None:
        row = r.model_dump(mode="json")
        await self._insert("markets", row, upsert=True)

    async def append_snapshot(self, s: MarketSnapshot) -> None:
        await self._insert("market_snapshots", s.model_dump(mode="json"))

    async def get_market(self, market_id: str) -> MarketRecord | None:
        rows = await self._select("markets", {"market_id": f"eq.{market_id}", "limit": "1"})
        if not rows:
            return None
        d = rows[0]
        d["end_date"] = _dt(d.get("end_date"))
        d["discovered_at"] = _dt(d.get("discovered_at")) or datetime.utcnow()
        return MarketRecord(**d)

    async def get_market_history(self, market_id: str) -> list[MarketSnapshot]:
        rows = await self._select(
            "market_snapshots",
            {"market_id": f"eq.{market_id}", "order": "timestamp", "select": "*"},
        )
        out = []
        for d in rows:
            d.pop("id", None)
            d["timestamp"] = _dt(d.get("timestamp")) or datetime.utcnow()
            out.append(MarketSnapshot(**d))
        return out

    # ── trail ─────────────────────────────────────────────────────────────────

    async def append_trail_event(self, e: TrailEvent) -> None:
        await self._insert("trail_events", e.model_dump(mode="json"))

    async def get_decision_trail(self, decision_id: str) -> list[TrailEvent]:
        rows = await self._select(
            "trail_events", {"decision_id": f"eq.{decision_id}", "order": "timestamp"}
        )
        out = []
        for d in rows:
            d.pop("id", None)
            d["timestamp"] = _dt(d.get("timestamp")) or datetime.utcnow()
            out.append(TrailEvent(**d))
        return out

    # ── research ────────────────────────────────────────────────────────────────

    async def upsert_research(self, r: ResearchRecord) -> None:
        await self._insert("research_records", r.model_dump(mode="json"), upsert=True)

    async def append_source_attribution(self, r: SourceAttributionRecord) -> None:
        await self._insert("source_attributions", r.model_dump(mode="json"))

    async def append_data_source_use(self, r: DataSourceUseRecord) -> None:
        await self._insert("data_source_uses", r.model_dump(mode="json"))

    # ── risk / execution ──────────────────────────────────────────────────────

    async def upsert_risk_decision(self, r: RiskDecisionRecord) -> None:
        await self._insert("risk_decisions", r.model_dump(mode="json"), upsert=True)

    async def append_fill(self, r: FillRecord) -> None:
        await self._insert("fills", r.model_dump(mode="json"))

    async def append_outcome(self, r: OutcomeRecord) -> None:
        await self._insert("outcomes", r.model_dump(mode="json"))

    # ── daily pnl ───────────────────────────────────────────────────────────────

    async def get_daily_loss(self, day: str) -> float:
        rows = await self._select("daily_pnl", {"day": f"eq.{day}", "select": "realised"})
        return float(rows[0]["realised"]) if rows else 0.0

    async def add_daily_pnl(self, day: str, realised: float) -> None:
        r = await self.http.post(
            f"{self.rest}/rpc/add_daily_pnl", json={"p_day": day, "p_realised": realised}
        )
        r.raise_for_status()

    # ── task queue ──────────────────────────────────────────────────────────────

    async def enqueue_task(self, task: TaskRecord) -> None:
        await self._insert("tasks", task.model_dump(mode="json"))

    async def claim_task(self, task_type: str, worker_pid: int) -> TaskRecord | None:
        r = await self.http.post(
            f"{self.rest}/rpc/claim_task",
            json={"p_task_type": task_type, "p_worker_pid": worker_pid},
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return None
        return self._task_from_row(rows[0])

    async def complete_task(self, task_id: str, output: dict[str, Any]) -> None:
        await self._patch("tasks", {"id": f"eq.{task_id}"}, {
            "status": "done", "output_payload": output,
            "completed_at": datetime.utcnow().isoformat(),
        })

    async def fail_task(self, task_id: str, error: str) -> None:
        await self._patch("tasks", {"id": f"eq.{task_id}"}, {
            "status": "failed", "error": error,
            "completed_at": datetime.utcnow().isoformat(),
        })

    async def get_task(self, task_id: str) -> TaskRecord | None:
        rows = await self._select("tasks", {"id": f"eq.{task_id}", "limit": "1"})
        return self._task_from_row(rows[0]) if rows else None

    def _task_from_row(self, d: dict) -> TaskRecord:
        for f in ("created_at", "claimed_at", "completed_at"):
            d[f] = _dt(d.get(f))
        return TaskRecord(**d)

    # ── read queries (dashboard API) ──────────────────────────────────────────

    async def list_fills(self) -> list[FillRecord]:
        rows = await self._select("fills", {"order": "timestamp", "select": "*"})
        out = []
        for d in rows:
            d.pop("id", None)
            d["timestamp"] = _dt(d.get("timestamp")) or datetime.utcnow()
            out.append(FillRecord(**d))
        return out

    async def list_outcomes(self) -> list[OutcomeRecord]:
        rows = await self._select("outcomes", {"order": "recorded_at", "select": "*"})
        out = []
        for d in rows:
            d.pop("id", None)
            d["recorded_at"] = _dt(d.get("recorded_at")) or datetime.utcnow()
            out.append(OutcomeRecord(**d))
        return out

    async def get_fill_by_decision(self, decision_id: str) -> FillRecord | None:
        rows = await self._select(
            "fills", {"decision_id": f"eq.{decision_id}", "order": "timestamp.desc", "limit": "1"}
        )
        if not rows:
            return None
        d = rows[0]; d.pop("id", None)
        d["timestamp"] = _dt(d.get("timestamp")) or datetime.utcnow()
        return FillRecord(**d)

    async def get_outcome_by_decision(self, decision_id: str) -> OutcomeRecord | None:
        rows = await self._select(
            "outcomes", {"decision_id": f"eq.{decision_id}", "order": "recorded_at.desc", "limit": "1"}
        )
        if not rows:
            return None
        d = rows[0]; d.pop("id", None)
        d["recorded_at"] = _dt(d.get("recorded_at")) or datetime.utcnow()
        return OutcomeRecord(**d)

    async def get_research(self, decision_id: str) -> ResearchRecord | None:
        rows = await self._select("research_records", {"decision_id": f"eq.{decision_id}", "limit": "1"})
        if not rows:
            return None
        d = rows[0]
        d["created_at"] = _dt(d.get("created_at")) or datetime.utcnow()
        return ResearchRecord(**d)

    async def get_risk_decision(self, decision_id: str) -> RiskDecisionRecord | None:
        rows = await self._select("risk_decisions", {"decision_id": f"eq.{decision_id}", "limit": "1"})
        if not rows:
            return None
        d = rows[0]
        d["created_at"] = _dt(d.get("created_at")) or datetime.utcnow()
        return RiskDecisionRecord(**d)

    async def get_source_attributions(self, decision_id: str) -> list[SourceAttributionRecord]:
        rows = await self._select("source_attributions", {"decision_id": f"eq.{decision_id}"})
        out = []
        for d in rows:
            d.pop("id", None)
            out.append(SourceAttributionRecord(**d))
        return out

    async def get_data_source_uses(self, decision_id: str) -> list[DataSourceUseRecord]:
        rows = await self._select("data_source_uses", {"decision_id": f"eq.{decision_id}"})
        out = []
        for d in rows:
            d.pop("id", None)
            d["fetched_at"] = _dt(d.get("fetched_at")) or datetime.utcnow()
            out.append(DataSourceUseRecord(**d))
        return out

    async def get_latest_trail_timestamp(self) -> datetime | None:
        rows = await self._select(
            "trail_events", {"order": "timestamp.desc", "limit": "1", "select": "timestamp"}
        )
        return _dt(rows[0]["timestamp"]) if rows else None

    async def close(self) -> None:
        await self.http.aclose()
