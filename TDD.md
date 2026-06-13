# Technical Design Document — Honeybee

Autonomous long-tail prediction-market **research-as-a-service** agents.

> v2 — user-centric flow. The user holds funds and the prediction-market account.
> Agents do research, recommend trades, and earn reputation on-chain. They never custody user assets.

Companion to `PRD.md`.

---

## 0. Decisions locked in

| Area | Decision |
|---|---|
| Stack | Hybrid: **Python 3.11** (agents, LLM, research, API) + **TypeScript / Node 20** (wallet, attestations, broker connectors) + **Next.js 14** (frontend) |
| Venues | `VenueAdapter` ABC; adapters for Polymarket, Kalshi, Gemini |
| LLMs | Router: cheap triage → escalate strong; mock fallback when keys absent |
| Capital | **User keeps custody.** Agent never holds user trade funds. Agent's own wallet holds only fee revenue + x402 budget. |
| Trade execution | **Per-agent toggle** — Manual approval (modal) OR Auto-execute up to user-set limits |
| Onchain anchoring | **Arc testnet, real writes** (Solidity `AttestationRegistry`) |
| User wallet | **Privy** — supports embedded + external (MetaMask, Coinbase Wallet) via single SDK |
| State | SQLite ledger; on-chain attestations are the source of truth for reputation |
| IPC | Python ↔ TS over local HTTP on `127.0.0.1` |

---

## 1. End-to-end user flow

```
1. USER connects wallet (Privy) on frontend
2. USER browses MARKETPLACE → picks an Agent (by ENS, reputation, win-rate)
3. USER pays Agent (USDC on Arc, x402) for a research run on a specific market
4. AGENT:
     a. checks ResearchCache: if hash already attested by another agent → reuse
     b. else: runs Discovery → Data → LLM Research → writes ResearchAttestation on Arc
     c. may call PEER AGENTS via x402 for sub-tasks (e.g. politics specialist)
     d. returns signed TradeRecommendation to user
5. EXECUTION:
     - Manual mode: frontend shows recommendation → user clicks "Approve" → broker connector submits trade USING USER'S broker creds → TradeAttestation written on Arc
     - Auto mode: if within user-configured limits → broker connector fires immediately → TradeAttestation written
6. RESOLUTION (async, when the market resolves):
     - Resolution watcher detects outcome → writes ResolutionAttestation with realised P&L
     - Agent's ENS reputation profile aggregates wins/losses
```

---

## 2. System architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                       Next.js Frontend (port 3000)                     │
│  Privy connect · Marketplace · Hire agent · Approve trade · Dashboard  │
└─────────────────┬──────────────────────────────────┬───────────────────┘
                  │ REST                              │ Privy SDK
                  ▼                                  ▼
        ┌────────────────────┐              ┌────────────────────┐
        │  Python API :8000  │              │  TS Service :8787  │
        │  /agents /research │◄────────────►│  /wallet /attest   │
        │  /pay /recommend   │              │  /broker /resolve  │
        └─────────┬──────────┘              └─────────┬──────────┘
                  │                                   │
                  ▼                                   ▼
   ┌─────────────────────────┐         ┌──────────────────────────┐
   │ Orchestrator + agents   │         │ Privy wallet (Arc)       │
   │  Discovery · Data       │         │ AttestationRegistry      │
   │  Research · Risk        │         │ Broker connectors        │
   │  LLM router · Ledger    │         │  - Polymarket            │
   └─────────────────────────┘         │  - Kalshi                │
                                       │  - Gemini                │
                                       └──────────────────────────┘
                                                  │
                                                  ▼
                                          ARC TESTNET
                                  (AttestationRegistry.sol)
```

---

## 3. Canonical data types

```python
# Research output (signed by agent, paid by user)
@dataclass
class Recommendation:
    rec_id: str                       # uuid; idempotency key
    agent_ens: str
    user_address: str                 # who paid for it
    market: Market
    outcome: str
    side: Literal["BUY","SELL"]
    fair_price: float                 # agent's true probability
    market_price: float               # at time of research
    edge: float                       # fair - market
    confidence: float                 # 0..1
    suggested_size_usd: float         # capped by user's per-agent limit
    rationale: str
    sources: list[str]
    research_hash: str                # sha256 of inputs+outputs → on-chain anchor
    research_attestation_tx: str | None  # arc tx hash after anchoring
    ts: datetime
    expires_at: datetime              # recommendations stale after N minutes

# Three attestation kinds, all on Arc
@dataclass
class ResearchAttestation:
    agent_ens: str
    market_id: str
    research_hash: str    # bytes32
    cost_paid_usd: float
    tx_hash: str
    block: int

@dataclass
class TradeAttestation:
    rec_id: str
    agent_ens: str
    user_address: str
    market_id: str
    side: str
    avg_price: float
    size_usd: float
    broker_tx_ref: str    # off-chain venue order id
    tx_hash: str

@dataclass
class ResolutionAttestation:
    trade_attestation_tx: str
    market_id: str
    resolved_outcome: str
    pnl_usd: float
    tx_hash: str
```

---

## 4. Components (deltas from v1)

### 4.1 Research caching + anchoring

Hash inputs deterministically so two agents querying the same market with same context produce the same `research_hash`. Before doing work, ping the on-chain registry:

```
research_hash = sha256(market_id || question || price_snapshot || context_bundle_hash)
if registry.hasResearch(research_hash):
    fetch cached IPFS/blob → skip recompute, charge user discounted rate
else:
    run pipeline → write attestation → emit Recommendation
```

For MVP we store the cached blob in SQLite; only the *hash* lives on Arc.

### 4.2 Agent → agent x402

`Research Agent` can decide it needs a specialist (e.g. a politics-tuned peer). It calls peer's `/research/:market_id` with an x402 `Payment` header. Peer responds either with `402 Payment Required` (quote) or `200 OK` (after settlement).

```
GET /research/sports.nba/0xMarket42  HTTP/1.1
X-PAYMENT: <x402 payment payload, USDC on Arc>
```

Per-agent daily x402 budget enforced by `RiskAgent` (already in schema).

### 4.3 Broker connectors (NEW)

In `execution/src/broker/`, one module per venue:

```ts
interface BrokerConnector {
  venue: 'polymarket' | 'kalshi' | 'gemini';
  // Uses USER's credentials passed per-call; never stored agent-side.
  submitAsUser(args: {
    userCreds: BrokerCreds;   // venue-specific
    rec: Recommendation;
    maxSlippageBps: number;
  }): Promise<BrokerFill>;
}
```

User credentials live in the user's browser (Privy/local storage). The TS service receives them per-call, uses them once, never persists.

### 4.4 AttestationRegistry contract (NEW)

```solidity
// AttestationRegistry.sol — deployed on Arc testnet
contract AttestationRegistry {
    event ResearchAttested(bytes32 indexed hash, address indexed agent, string ens, string marketId, uint256 timestamp);
    event TradeAttested(bytes32 indexed recId, address indexed agent, address user, string marketId, uint8 side, uint256 priceE6, uint256 sizeUsdE6, uint256 timestamp);
    event ResolutionAttested(bytes32 indexed tradeRef, string resolvedOutcome, int256 pnlUsdE6, uint256 timestamp);

    mapping(bytes32 => bool) public hasResearch;
    mapping(bytes32 => bool) public hasTrade;

    function attestResearch(bytes32 hash, string calldata ens, string calldata marketId) external { ... }
    function attestTrade(bytes32 recId, address user, string calldata marketId, uint8 side, uint256 priceE6, uint256 sizeUsdE6) external { ... }
    function attestResolution(bytes32 tradeRef, string calldata resolvedOutcome, int256 pnlUsdE6) external { ... }
}
```

Each agent's Privy wallet on Arc is the `msg.sender`. ENS subname lookup off-chain via Ethereum mainnet (ENS canonical).

### 4.5 Reputation aggregator

Off-chain indexer (Python) scans `AttestationRegistry` events for an agent's address, aggregates:
- `total_recommendations`, `total_resolved`, `wins`, `losses`
- `realised_pnl_usd`, `avg_edge`, `avg_confidence_calibration`

Exposed via `/agents/:ens/reputation`.

---

## 5. Repo layout (final)

```
Honeybee/
├── PRD.md
├── TDD.md
├── Makefile
├── .env.example
├── pyproject.toml
├── package.json                     # TS workspace
│
├── agents/                          # Python
│   └── honeybee/
│       ├── config.py, ledger.py
│       ├── api.py                   # HTTP API for frontend
│       ├── orchestrator.py          # research loop (no auto-trade)
│       ├── reputation.py            # event indexer (NEW)
│       ├── llm/                     # router + clients
│       ├── venues/                  # market data adapters
│       ├── agents/
│       │   ├── discovery.py
│       │   ├── data_agent.py
│       │   ├── research.py
│       │   ├── risk.py              # sizing only; no execution
│       │   ├── peer_call.py         # x402 client to call other agents (NEW)
│       │   └── recommender.py       # builds + signs Recommendations (NEW)
│       └── skills/
│
├── execution/                       # TypeScript
│   └── src/
│       ├── server.ts
│       ├── wallet/                  # Privy
│       ├── chain/
│       │   ├── attestation.ts       # AttestationRegistry client (NEW)
│       │   └── arc.ts               # viem client for Arc (NEW)
│       ├── broker/                  # User-creds trade submission (NEW)
│       │   ├── polymarket.ts
│       │   ├── kalshi.ts
│       │   └── gemini.ts
│       └── paper.ts
│
├── contracts/                       # Solidity (NEW)
│   ├── AttestationRegistry.sol
│   ├── foundry.toml
│   └── scripts/deploy.ts
│
├── web/                             # Next.js
│   ├── app/
│   │   ├── page.tsx                 # dashboard
│   │   ├── marketplace/             # browse agents + reputation
│   │   ├── agents/[ens]/            # agent detail + hire
│   │   ├── trades/                  # pending recommendations needing approval
│   │   └── settings/                # connect wallet, per-agent limits
│   └── components/
│
└── shared/schema.json
```

---

## 6. Non-functional targets (unchanged)

| Metric | Target |
|---|---|
| Cost per triage decision | < $0.001 |
| Cost per deep analysis | < $0.01 |
| Time from `pay` → recommendation | < 30 s |
| Crash recovery | < 5 s, no duplicate trades (idempotency on `rec_id`) |
| Per-agent x402 daily budget | enforced both client- and server-side |

---

## 7. Security model

| Boundary | Mechanism |
|---|---|
| User funds | Never leave user's wallet / broker account |
| User broker creds | Passed per-request, never persisted server-side |
| Agent private keys | Privy TEE; never in our process memory |
| Auto-execute limits | Enforced by `RiskAgent` AND server-side `/broker/submit` AND on-chain contract guard |
| Replay protection | `rec_id` is sha-256 of (agent || market || timestamp || user); registry rejects duplicates |
| Trust between agents | Reputation = on-chain attestation history. No off-chain trust assumption. |

---

## 8. Demo script (end-to-end)

```
1. Open http://localhost:3000
2. Connect Privy wallet (or paste demo address)
3. Go to /marketplace, see 3 demo agents with reputation badges
4. Click "alpha-trader.honeybee.agent.eth" → details + sample track record
5. Click "Hire — $0.05 / market", select a Polymarket market
6. (background) x402 settlement on Arc testnet → research pipeline runs
7. Recommendation card appears with fair price, edge, confidence, rationale
8. Click "Approve & Execute" → broker connector submits via user's Polymarket creds
9. TradeAttestation tx hash shown, linked to Arc explorer
10. (later) when market resolves, ResolutionAttestation fires; agent's reputation updates
```
