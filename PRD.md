# PRD — Autonomous Long-Tail Prediction Market Trading Agent

> Source-of-truth product brief. See `TDD.md` for the implementation design.

## 1. Executive Summary & Core Philosophy

High-liquidity prediction markets are a battleground for high-frequency quant firms fighting over milliseconds. In contrast, the long tail of niche, low-liquidity prediction markets remains entirely unserved. The profit-per-market is too low to justify human analysts, leaving massive informational mispricings completely unchecked.

This project builds an autonomous, multi-agent system to discover, analyze, and trade across thousands of these niche markets simultaneously.

**Edge:** not latency — *coverage* and the collapse of reasoning costs. LLMs drive the marginal cost of analysis to near zero, letting the agent profitably trade markets that are too small for traditional quant funds to staff.

## 2. Multi-Agent Architecture

Hierarchical orchestrator → specialised sub-agents:

- **Market Discovery (P0)** — scans venue registries; flags low-volume, wide-spread, or unpriced contracts.
- **Research (P0)** — vertical reasoning (sports, politics, etc.) using live search and social signals.
- **Data (P0)** — maps query → required data pipelines (APIs, RSS, stats feeds).
- **Execution & Risk (P0)** — fractional Kelly sizing, embedded wallet signing.
- **Correlated Market & Arbitrage (P1)** — cross-market structural contradictions.

## 3. Core Features

### P0 (MVP)
- Continuous 24/7 agent runtime, MCP-style pluggable skills, crash-safe state ledger.
- Unified prediction market integration (Gemini, plus Polymarket/Kalshi via venue adapter).
- Decentralised identity via ENS (`*.agent.eth`).
- Embedded agent wallets (Privy / Dynamic / Blink) for self-signing.
- Multi-chain settlement abstraction (Hedera, World/Arc).

### P1
- Backtesting / simulation sandbox over historical resolved markets.
- ERC-8004 reputation marketplace on Google Cloud.
- Data streaming marketplace via X402 bazaar.

## 4. Non-Functional

- **Cost per decision**, not latency, is the primary metric. Target < $0.001 per triage loop.
- Private keys isolated in secure enclaves (Privy TEE / cloud KMS).
- Hard circuit breakers: per-market exposure cap, daily loss kill-switch, slippage controls.
