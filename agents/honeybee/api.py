"""Lightweight HTTP API the frontend talks to.

We avoid adding FastAPI/Uvicorn as a hard dep — use stdlib `http.server`
running on a thread, with permissive CORS so Next.js dev server (`:3000`)
can call us directly.

Endpoints
---------
GET    /health
GET    /agents
POST   /agents
GET    /agents/{ens}
PATCH  /agents/{ens}
GET    /agents/{ens}/reputation
GET    /fills?limit=N
GET    /markets/top
POST   /pay
POST   /research                  user pays an agent for research on a market
GET    /recommendations           list, filterable by user_address/agent_ens/status
POST   /recommendations/{rec_id}/approve   user approves → broker submit + anchor
POST   /recommendations/{rec_id}/reject
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiosqlite
import httpx

from .config import CONFIG
from .ledger import Ledger

log = logging.getLogger(__name__)

API_PORT = 8000


# ─────────── async helpers run via a private event loop on a worker thread ──
import asyncio

_loop: asyncio.AbstractEventLoop | None = None


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        t = threading.Thread(target=_loop.run_forever, daemon=True)
        t.start()
    return _loop


def _run(coro):
    loop = _ensure_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=20)


# ─────────── data access ──────────────────────────────────────────────────
LEDGER = Ledger()


async def _init() -> None:
    await LEDGER.init()
    # Agents table holds the user-configurable strategy params.
    async with aiosqlite.connect(LEDGER.path) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            ens               TEXT PRIMARY KEY,
            label             TEXT NOT NULL,
            wallet_id         TEXT,
            wallet_address    TEXT,
            bankroll_usd      REAL NOT NULL DEFAULT 1000,
            kelly_fraction    REAL NOT NULL DEFAULT 0.25,
            confidence_floor  REAL NOT NULL DEFAULT 0.55,
            venue             TEXT NOT NULL DEFAULT 'polymarket',
            llm_tier          TEXT NOT NULL DEFAULT 'router',
            x402_daily_usd    REAL NOT NULL DEFAULT 5.0,
            paused            INTEGER NOT NULL DEFAULT 0,
            created_at        REAL NOT NULL DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              REAL NOT NULL DEFAULT (strftime('%s','now')),
            agent_ens       TEXT NOT NULL,
            from_address    TEXT NOT NULL,
            amount_usd      REAL NOT NULL,
            tx_hash         TEXT,
            kind            TEXT NOT NULL DEFAULT 'fund'   -- fund | hire | x402
        );
        """)
        await db.commit()


async def _list_agents() -> list[dict[str, Any]]:
    async with aiosqlite.connect(LEDGER.path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM agents ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
        out = []
        for r in rows:
            ens = r["ens"]
            async with db.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(json_extract(payload,'$.filled_usd')),0) AS notional "
                "FROM events WHERE kind='fill' AND market_id IN ("
                "SELECT market_id FROM events WHERE kind='agent_assignment' AND json_extract(payload,'$.ens')=?)",
                (ens,),
            ) as cur:
                stat = await cur.fetchone()
            async with db.execute(
                "SELECT COALESCE(SUM(amount_usd),0) AS funded FROM payments WHERE agent_ens=? AND kind='fund'",
                (ens,),
            ) as cur:
                funded = (await cur.fetchone())["funded"]
            d = dict(r)
            d["fills_count"] = int(stat["n"] or 0)
            d["notional_usd"] = float(stat["notional"] or 0)
            d["funded_usd"] = float(funded or 0)
            out.append(d)
        return out


async def _get_agent(ens: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(LEDGER.path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM agents WHERE ens=?", (ens,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return dict(row)


async def _create_agent(label: str, venue: str, bankroll: float, kelly: float,
                        conf: float, llm_tier: str, x402_daily: float) -> dict[str, Any]:
    parent = "honeybee.agent.eth"
    slug = "".join(c.lower() if c.isalnum() else "-" for c in label).strip("-") or "agent"
    ens = f"{slug}.{parent}"

    # Mint a Privy-managed wallet via the TS wallet service. Falls back to mock if down.
    wallet = {"id": None, "address": None}
    try:
        async with httpx.AsyncClient(timeout=5) as h:
            r = await h.post(f"{CONFIG.wallet_service_url}/wallet/create", json={"label": ens})
            if r.status_code == 200:
                wallet = r.json()
    except Exception as e:
        log.warning("wallet service unreachable on create_agent: %s", e)

    async with aiosqlite.connect(LEDGER.path) as db:
        await db.execute(
            """INSERT OR REPLACE INTO agents
               (ens, label, wallet_id, wallet_address, bankroll_usd, kelly_fraction,
                confidence_floor, venue, llm_tier, x402_daily_usd, paused)
               VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
            (ens, label, wallet.get("id"), wallet.get("address"),
             bankroll, kelly, conf, venue, llm_tier, x402_daily),
        )
        await db.commit()
    return await _get_agent(ens) or {}


async def _update_agent(ens: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"bankroll_usd", "kelly_fraction", "confidence_floor",
               "venue", "llm_tier", "x402_daily_usd", "paused"}
    sets, vals = [], []
    for k, v in patch.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(int(v) if k == "paused" else v)
    if not sets:
        return await _get_agent(ens)
    vals.append(ens)
    async with aiosqlite.connect(LEDGER.path) as db:
        await db.execute(f"UPDATE agents SET {', '.join(sets)} WHERE ens=?", vals)
        await db.commit()
    return await _get_agent(ens)


async def _recent_fills(limit: int = 50) -> list[dict[str, Any]]:
    async with aiosqlite.connect(LEDGER.path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT ts, market_id, payload FROM events WHERE kind='fill' ORDER BY id DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    out = []
    for r in rows:
        p = json.loads(r["payload"])
        p["ts"] = datetime.fromtimestamp(r["ts"], tz=timezone.utc).isoformat()
        out.append(p)
    return out


async def _record_payment(ens: str, from_addr: str, amount: float, tx: str | None, kind: str) -> dict[str, Any]:
    async with aiosqlite.connect(LEDGER.path) as db:
        await db.execute(
            "INSERT INTO payments (agent_ens, from_address, amount_usd, tx_hash, kind) VALUES (?,?,?,?,?)",
            (ens, from_addr, amount, tx, kind),
        )
        await db.commit()
    return {"ok": True, "agent": ens, "amount": amount, "kind": kind}


async def _top_markets() -> list[dict[str, Any]]:
    """Replay last discovery snapshot from the ledger."""
    async with aiosqlite.connect(LEDGER.path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT payload FROM events WHERE kind='discovery_snapshot' ORDER BY id DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return []
    return json.loads(row["payload"]).get("markets", [])


# Lazy orchestrator handle. We spin up a single Orchestrator inside the API
# process so paid research requests reuse all the LLM/venue/data wiring.
_ORCH = None


def _get_orch():
    global _ORCH
    if _ORCH is None:
        from .orchestrator import Orchestrator
        _ORCH = Orchestrator()
    return _ORCH


async def _reputation(ens: str) -> dict[str, Any]:
    async with aiosqlite.connect(LEDGER.path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT COUNT(*) AS n FROM recommendations WHERE agent_ens=?", (ens,)
        ) as cur:
            n_recs = (await cur.fetchone())["n"]
        async with db.execute(
            "SELECT COUNT(*) AS n FROM recommendations WHERE agent_ens=? AND status='executed'", (ens,)
        ) as cur:
            n_exec = (await cur.fetchone())["n"]
        async with db.execute(
            "SELECT COUNT(*) AS n FROM attestations WHERE agent_ens=? AND kind='resolution'", (ens,)
        ) as cur:
            n_res = (await cur.fetchone())["n"]
    return {
        "ens": ens,
        "recommendations": int(n_recs),
        "executed_trades": int(n_exec),
        "resolutions_anchored": int(n_res),
    }


async def _anchor(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    """Forward an anchor request to the TS wallet service. Mock-safe."""
    try:
        async with httpx.AsyncClient(timeout=15) as h:
            r = await h.post(f"{CONFIG.wallet_service_url}/attest/{kind}", json=body)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        log.warning("anchor %s failed (will use local mock): %s", kind, e)
    # Local mock fallback so the UI still shows a tx hash
    import hashlib as _h
    seed = json.dumps(body, sort_keys=True, default=str).encode()
    return {
        "tx_hash": "0x" + _h.sha256(seed).hexdigest(),
        "block_number": None,
        "chain_id": 0,
        "explorer_url": None,
        "mock": True,
    }


async def _broker_submit(rec: dict[str, Any], creds: dict[str, Any], user: str) -> dict[str, Any]:
    """Hand off to the TS service to submit using user creds + anchor trade."""
    # Autonomous/demo path: with no creds + a Kalshi rec, use the env Kalshi
    # (demo) creds so the agent places a REAL signed order, not a paper fallback.
    if not creds and rec.get("venue") == "kalshi" and CONFIG.kalshi_api_key_id:
        try:
            with open(CONFIG.kalshi_private_key_path) as f:
                creds = {"apiKeyId": CONFIG.kalshi_api_key_id, "privateKeyPem": f.read()}
        except Exception as e:
            log.warning("kalshi demo creds load failed: %s", e)
    try:
        async with httpx.AsyncClient(timeout=30) as h:
            r = await h.post(
                f"{CONFIG.wallet_service_url}/broker/submit",
                json={
                    "rec": {
                        "rec_id": rec["rec_id"],
                        "venue": rec["venue"],
                        "market_id": rec["market_id"],
                        "outcome": rec["outcome"],
                        "side": rec["side"],
                        "market_price": rec["market_price"],
                        "fair_price": rec["fair_price"],
                        "suggested_size_usd": rec["suggested_size_usd"],
                    },
                    "creds": creds or {},
                    "user": user,
                    "maxSlippageBps": 200,
                },
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.warning("broker submit failed (local paper fallback): %s", e)
        # Local fallback so the demo always completes
        return {
            "fill": {
                "rec_id": rec["rec_id"],
                "venue": rec["venue"],
                "market_id": rec["market_id"],
                "outcome": rec["outcome"],
                "side": rec["side"],
                "avg_price": rec["market_price"] + 0.01,
                "filled_usd": rec["suggested_size_usd"],
                "broker_ref": "local-paper-" + rec["rec_id"][:8],
            },
            "attestation": await _anchor("trade", {
                "recId": rec["rec_id"],
                "user": user,
                "marketId": rec["market_id"],
                "side": rec["side"],
                "price": rec["market_price"] + 0.01,
                "sizeUsd": rec["suggested_size_usd"],
            }),
        }


async def _research_for_user(user_address: str, agent_ens: str, venue: str,
                             market_id: str) -> dict[str, Any]:
    """Top-level: user pays → orchestrator runs research → anchor + persist."""
    orch = _get_orch()
    # Find or fetch the Market object from the right venue adapter.
    market = None
    for v in orch.venues:
        if v.name != venue:
            continue
        ms = await v.list_markets(limit=500)
        market = next((m for m in ms if m.market_id == market_id), None)
        if market:
            break
    if market is None:
        return {"error": f"market {market_id} not found on {venue}"}

    rec = await orch.research_market(
        market=market, user_address=user_address, agent_ens=agent_ens,
    )
    if rec is None:
        return {"error": "research did not produce a recommendation (no edge / low confidence)"}

    # Anchor research on Arc (mock-safe).
    attest = await _anchor("research", {
        "researchHash": rec["research_hash"],
        "ens": agent_ens,
        "marketId": market_id,
    })
    rec["research_attestation_tx"] = attest.get("tx_hash")
    await LEDGER.save_recommendation(rec)
    await LEDGER.save_attestation(
        kind="research", tx_hash=attest["tx_hash"], payload=rec,
        agent_ens=agent_ens, user_address=user_address, market_id=market_id,
        block_number=attest.get("block_number"),
        chain_id=int(attest.get("chain_id", 0)),
    )
    return rec


async def _approve_recommendation(rec_id: str, creds: dict[str, Any]) -> dict[str, Any]:
    rec = await LEDGER.get_recommendation(rec_id)
    if not rec:
        return {"error": "not found"}
    if rec["status"] not in ("pending",):
        return {"error": f"cannot approve recommendation in status {rec['status']}"}
    result = await _broker_submit(rec, creds, rec["user_address"])
    await LEDGER.update_recommendation_status(rec_id, "executed")
    attest = result.get("attestation") or {}
    await LEDGER.save_attestation(
        kind="trade", tx_hash=attest.get("tx_hash", "0x0"), payload=result,
        agent_ens=rec["agent_ens"], user_address=rec["user_address"],
        market_id=rec["market_id"], block_number=attest.get("block_number"),
        chain_id=int(attest.get("chain_id", 0)),
    )
    return result


async def _reject_recommendation(rec_id: str) -> dict[str, Any]:
    await LEDGER.update_recommendation_status(rec_id, "rejected")
    return {"ok": True}


# ─────────── HTTP handler ─────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # quieter
        log.info("api %s - %s", self.address_string(), fmt % args)

    # CORS preflight
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")

    def _json(self, status: int, body: Any) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path.rstrip("/")
        q = parse_qs(u.query)
        try:
            if path == "/health":
                return self._json(200, {"ok": True, "dry_run": CONFIG.dry_run})
            if path == "/agents":
                return self._json(200, _run(_list_agents()))
            if path.startswith("/agents/") and path.endswith("/reputation"):
                ens = path[len("/agents/"):-len("/reputation")]
                return self._json(200, _run(_reputation(ens)))
            if path.startswith("/agents/"):
                ens = path.split("/agents/", 1)[1]
                a = _run(_get_agent(ens))
                return self._json(200 if a else 404, a or {"error": "not found"})
            if path == "/fills":
                limit = int((q.get("limit") or ["50"])[0])
                return self._json(200, _run(_recent_fills(limit)))
            if path == "/markets/top":
                return self._json(200, _run(_top_markets()))
            if path == "/recommendations":
                limit = int((q.get("limit") or ["50"])[0])
                recs = _run(LEDGER.list_recommendations(
                    user_address=(q.get("user_address") or [None])[0],
                    agent_ens=(q.get("agent_ens") or [None])[0],
                    status=(q.get("status") or [None])[0],
                    limit=limit,
                ))
                return self._json(200, recs)
            if path.startswith("/recommendations/"):
                rec_id = path.split("/recommendations/", 1)[1]
                r = _run(LEDGER.get_recommendation(rec_id))
                return self._json(200 if r else 404, r or {"error": "not found"})
            return self._json(404, {"error": "not found"})
        except Exception as e:
            log.exception("GET %s failed", path)
            return self._json(500, {"error": str(e)})

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path.rstrip("/")
        body = self._body()
        try:
            if path == "/agents":
                a = _run(_create_agent(
                    label=str(body.get("label") or "agent"),
                    venue=str(body.get("venue") or "polymarket"),
                    bankroll=float(body.get("bankroll_usd") or 1000),
                    kelly=float(body.get("kelly_fraction") or 0.25),
                    conf=float(body.get("confidence_floor") or 0.55),
                    llm_tier=str(body.get("llm_tier") or "router"),
                    x402_daily=float(body.get("x402_daily_usd") or 5.0),
                ))
                return self._json(201, a)
            if path == "/pay":
                r = _run(_record_payment(
                    ens=str(body.get("agent_ens") or ""),
                    from_addr=str(body.get("from_address") or "0x0"),
                    amount=float(body.get("amount_usd") or 0),
                    tx=body.get("tx_hash"),
                    kind=str(body.get("kind") or "fund"),
                ))
                return self._json(200, r)
            if path == "/research":
                # User pays for a research run. Record the payment first, then run.
                user = str(body.get("user_address") or "0xUnknown")
                ens = str(body.get("agent_ens") or "")
                venue = str(body.get("venue") or "polymarket")
                market_id = str(body.get("market_id") or "")
                if not ens or not market_id:
                    return self._json(400, {"error": "agent_ens and market_id required"})
                price = float(body.get("price_usd") or 0.05)
                _run(_record_payment(
                    ens=ens, from_addr=user, amount=price,
                    tx=body.get("tx_hash") or "x402-mock",
                    kind="hire",
                ))
                rec = _run(_research_for_user(user, ens, venue, market_id))
                return self._json(200, rec)
            if path.startswith("/recommendations/") and path.endswith("/approve"):
                rec_id = path[len("/recommendations/"):-len("/approve")]
                creds = body.get("creds") or {}
                return self._json(200, _run(_approve_recommendation(rec_id, creds)))
            if path.startswith("/recommendations/") and path.endswith("/reject"):
                rec_id = path[len("/recommendations/"):-len("/reject")]
                return self._json(200, _run(_reject_recommendation(rec_id)))
            return self._json(404, {"error": "not found"})
        except Exception as e:
            log.exception("POST %s failed", path)
            return self._json(500, {"error": str(e)})

    def do_PATCH(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path.rstrip("/")
        body = self._body()
        if path.startswith("/agents/"):
            ens = path.split("/agents/", 1)[1]
            a = _run(_update_agent(ens, body))
            return self._json(200 if a else 404, a or {"error": "not found"})
        return self._json(404, {"error": "not found"})


def serve(port: int = API_PORT) -> None:
    logging.basicConfig(level=CONFIG.log_level, format="[api] %(levelname)s %(message)s")
    _run(_init())
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    log.info("honeybee API listening on http://127.0.0.1:%d", port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    serve()
