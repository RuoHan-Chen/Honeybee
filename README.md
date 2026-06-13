# Honeybee

Autonomous, multi-agent system that trades the long tail of low-liquidity prediction markets.

The edge is **coverage and cost**, not speed: LLMs collapse the cost of reasoning to near zero, so the agent can profitably discover, price, and trade thousands of niche markets no human analyst would staff.

> The canonical implementation is in **`src/`** (this README). The older `agents/honeybee/` tree is a prior prototype.

## Architecture

Each agent is its **own OS process**. They communicate through a **SQLite task queue** (a `tasks` table in the Repository, WAL mode + atomic `BEGIN IMMEDIATE` claims) — no microservices, no HTTP, no external broker. Every inter-agent message and every reasoning step is persisted to a **decision trail** keyed by `decision_id`, so the frontend can later render exactly why each trade was made.

```
Orchestrator (mints decision_id per market, spawns + supervises agents)
  └─> Discovery   process  — Gamma API → ranked candidates  (no LLM)
        └─> Data        process — fetches free sources → DataBundle
        └─> Research    process — Anthropic (haiku triage → sonnet deep) → fair value
        └─> Execution   process — Kelly sizing + risk checks → PaperWallet/LiveWallet
        └─> Arbitrage   process — P1 stub
```

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # add ANTHROPIC_API_KEY

python -m src.main                                # paper trading (default, no real funds)
```

On Windows set `PYTHONUTF8=1` (the entrypoints also force UTF-8) so trail arrows (`→`) render.

- **Paper by default.** Real order submission is gated behind `--live` *and* `POLYMARKET_PRIVATE_KEY`.
- **No keys?** Add an Anthropic key for real analysis; without it the Research Agent cannot run (Anthropic-only).
- **Cost-per-cycle** is logged every loop.

## Layout

```
config/mandate.yaml         risk limits, verticals, discovery filters (NOT secrets)
src/
  main.py                   entrypoint — parses --live, starts Orchestrator
  contracts.py              pydantic v2 models passed between agents
  orchestrator.py           spawns agent processes, mints decision_id, drives the loop
  agents/
    discovery.py            Market Discovery Agent  (no LLM)
    data.py                 Data Agent              (free sources; x402 paid = P1)
    research.py             Research Agent          (Anthropic haiku→sonnet)
    execution.py            Execution & Risk Agent
    arbitrage.py            Correlated/Arbitrage Agent (P1 stub)
  venue/
    polymarket.py           Gamma + CLOB read-only
    wallet.py               PaperWallet (default) / LiveWallet (EIP-712, P1)
  risk/sizing.py            fractional Kelly, circuit breakers, slippage guard
  store/
    repository.py           abstract Repository interface + record models
    sqlite_repo.py          default SqliteRepository [PLACEHOLDER — swap for Postgres]
  backtest/harness.py       replay resolved markets → calibration report + EV
tests/
var/                        SQLite ledger (gitignored)
```

## The decision trail

Every agent appends `TrailEvent`s tied to a `decision_id`:

```
[orchestrator] Evaluating: Will Bitcoin close above $150k by end of 2026?
[data]         Pulled coingecko via free (free)
[research]     Triage (haiku): worth_deep=True, quick_fair=0.350
[research]     coingecko shifted fair value 0.300 → 0.280 (-0.020): magnitude of gain needed…
[research]     Deep analysis (sonnet): fair_value=0.280, confidence=0.52
[execution]    Skipped: confidence below floor
```

Reconstruct any trade's full story with `Repository.get_decision_trail(decision_id)`.

## Dashboard (read-only)

A thin FastAPI read layer (`src/api/`) exposes the Repository as JSON; a Vite + React + TS
dashboard (`dashboard/`) renders P&L, exposure by category, open/resolved positions, and a
full per-trade **decision audit** (sources + costs + fair-value deltas + risk checks). It never
writes and never trades.

```bash
# 1. seed some decision trails so there's data to show
python -m src.seed_dashboard

# 2. API (terminal 1)
uvicorn src.api.app:app --port 8000        # PYTHONUTF8=1 on Windows

# 3. dashboard (terminal 2)
cd dashboard && npm install && npm run dev  # → http://localhost:5173 (proxies /api → :8000)
```

## Storage backend — SQLite ↔ Supabase (Postgres)

Storage is behind the `Repository` interface; pick the backend with `REPO_BACKEND`:

- `REPO_BACKEND=sqlite` (default) — the local placeholder (`var/honeybee.db`).
- `REPO_BACKEND=supabase` — real Postgres via Supabase. One-time setup: run
  `config/supabase_schema.sql` in the Supabase SQL Editor, set `SUPABASE_URL` +
  `SUPABASE_SERVICE_ROLE_KEY` in `.env`, then `REPO_BACKEND=supabase python -m src.seed_dashboard`
  and start the API. No agent code changes — `src/store/factory.py` does the swap.

The `service_role` key is server-side only (it's in `.env`, gitignored). The browser/dashboard
only ever needs the publishable/anon key.

## Backtest / calibration gate

```bash
python -m src.backtest.harness
```

Replays resolved markets through the Research Agent and prints a calibration report + estimated EV. **Do not enable `--live` until calibration looks sane.**

## Live trading & US access

`LiveWallet` (EIP-712 signing via `py_clob_client`) is a P1 stub. Polymarket is non-custodial on Polygon; the agent signs its own orders. **US access runs through a KYC'd, CFTC-regulated entity** — the wallet still signs but the account is identity-bound. KYC is manual and intentionally not automated.

## Config & secrets

- `config/mandate.yaml` — bankroll, Kelly fraction, caps, edge/confidence thresholds, discovery filters, verticals, cadence.
- `.env` — secrets only (`ANTHROPIC_API_KEY`, `POLYMARKET_PRIVATE_KEY`, `DATABASE_URL`). Never commit.
