# Honeybee

Autonomous long-tail prediction market trading agent.

See `PRD.md` for product context, `TDD.md` for architecture.

## Quick start

```bash
cp .env.example .env                # fill in keys when you have them
make setup                          # python venv + npm install
make wallet &                       # start TS wallet/execution service on :8787
make demo                           # run the orchestrator loop (paper trading)
```

`DRY_RUN=true` by default — paper trading against live Polymarket orderbooks. No keys required to run the demo; the LLM router falls back to a deterministic mock so the full pipeline executes end-to-end out of the box.

## Layout

```
agents/         Python agents (orchestrator, research, risk, venues)
execution/      TypeScript wallet + signing service (Privy, ENS)
shared/         Canonical JSON schemas
infra/          Compose files
var/            SQLite ledger (gitignored)
```
