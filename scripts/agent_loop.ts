/**
 * Autonomous trading-agent loop.
 *
 * Runs as `alpha-trader`. Every TICK_SEC, it:
 *
 *   1. Picks a market id (rotating through a tiny built-in list — replace with
 *      a real venue feed when wiring to production).
 *   2. DISCOVERS its analyst counterparties by resolving their ENS subnames on
 *      Sepolia L1. The roster file is treated as a *cache* of the agent's own
 *      Privy walletId, NOT as the source of truth for who-is-who. The
 *      analyst's Arc address is whatever Sepolia ENS says it is.
 *   3. Calls /agent/by-address/<arcAddr>/signal for each analyst
 *        (402 → pays USDC via Privy → retries with X-PAYMENT)
 *   4. Blends the two fair prices (confidence-weighted).
 *   5. Anchors a research attestation on Arc (Privy-signed by alpha-trader
 *      so the AttestationRegistry identity-binding check passes).
 *   6. If |fair - market_price| > EDGE_THRESHOLD, simulates a paper trade and
 *      anchors a trade attestation on Arc (Privy-signed).
 *   7. Every RESOLUTION_EVERY ticks, picks the oldest open trade, flips a
 *      coin to settle it, and anchors a resolution attestation on Arc.
 *
 * Every step emits an activity event to the wallet service's SSE bus over HTTP
 * so the /fleet UI ticker sees the full loop in real time.
 */
import 'dotenv/config';
import { fetchWithX402 } from '../execution/src/x402/client.js';
import { findAgent } from '../execution/src/agents/registry.js';
import { resolveEnsOnSepolia } from '../execution/src/wallet/ens.js';
import { createHash, randomUUID } from 'node:crypto';

const WALLET_BASE = process.env.WALLET_SERVICE_URL ?? 'http://127.0.0.1:8787';
const TICK_SEC = Number(process.env.AGENT_LOOP_TICK_SEC ?? 30);
const MAX_USDC_PER_TICK = Number(process.env.AGENT_LOOP_MAX_USDC ?? 0.02);
const EDGE_THRESHOLD = Number(process.env.AGENT_LOOP_EDGE_THRESHOLD ?? 0.08);
const RESOLUTION_EVERY = Number(process.env.AGENT_LOOP_RESOLUTION_EVERY ?? 3);
const ENS_PARENT = process.env.ENS_SEPOLIA_NAME ?? 'honeybee-agents.eth';

// The analyst roster, expressed as ENS subnames on Sepolia. The loop has
// NO local knowledge of these agents' Arc addresses — those are discovered
// at tick-time by resolving the ENS name on Sepolia L1.
const ANALYST_ENS_NAMES = [
  `sports-analyst.${ENS_PARENT}`,
  `politics-analyst.${ENS_PARENT}`,
];

// Demo markets — replace with a venue list call when wiring to prod.
const MARKETS = [
  'will-arsenal-beat-chelsea-2026-07-04',
  'us-cpi-yoy-jun-2026-above-3pct',
  'btc-above-100k-by-2026-q4',
  'fed-cuts-25bps-by-aug-2026',
];

interface Signal {
  fair_yes: number;
  confidence: number;
  agent: string;
  marketId: string;
}

interface OpenTrade {
  recId: string;
  marketId: string;
  side: 'BUY' | 'SELL';
  price: number;
  sizeUsd: number;
  openedAt: number;
}

// ─── helpers (HTTP wrappers for wallet svc) ────────────────────────────────

async function emitRemote(ev: {
  kind: 'agent.action' | 'attestation';
  actor?: string;
  counterparty?: string;
  summary: string;
  details?: Record<string, unknown>;
}) {
  try {
    await fetch(`${WALLET_BASE}/activity`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(ev),
    });
  } catch (err) {
    console.error(`  [activity] publish failed:`, (err as Error).message);
  }
}

async function anchorResearchRemote(input: { researchHash: string; ens: string; marketId: string }):
  Promise<{ tx_hash: string; mock: boolean; explorer_url: string | null }> {
  const r = await fetch(`${WALLET_BASE}/attest/research`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(`attest/research ${r.status}: ${await r.text()}`);
  return r.json();
}

async function anchorTradeRemote(input: {
  recId: string; ens: string; user: `0x${string}`; marketId: string;
  side: 'BUY' | 'SELL'; price: number; sizeUsd: number;
}): Promise<{ tx_hash: string; mock: boolean; explorer_url: string | null }> {
  const r = await fetch(`${WALLET_BASE}/attest/trade`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(`attest/trade ${r.status}: ${await r.text()}`);
  return r.json();
}

async function anchorResolutionRemote(input: {
  recId: string; resolvedOutcome: string; pnlUsd: number; ens: string;
}): Promise<{ tx_hash: string; mock: boolean; explorer_url: string | null }> {
  const r = await fetch(`${WALLET_BASE}/attest/resolution`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(`attest/resolution ${r.status}: ${await r.text()}`);
  return r.json();
}

// ─── ENS-based discovery ───────────────────────────────────────────────────

interface DiscoveredAgent { ensName: string; address: `0x${string}` }

/**
 * Resolve all analyst subnames on Sepolia L1. Cached for the lifetime of the
 * process — addresses don't change often, and we don't want to spam the
 * public Sepolia RPC. Cache miss on a name = that analyst is silently
 * skipped this tick (and an activity event flags the failure).
 */
const ensDiscoveryCache = new Map<string, `0x${string}`>();
async function discoverAnalystsViaEns(): Promise<DiscoveredAgent[]> {
  const out: DiscoveredAgent[] = [];
  for (const ensName of ANALYST_ENS_NAMES) {
    let addr = ensDiscoveryCache.get(ensName);
    if (!addr) {
      const resolved = await resolveEnsOnSepolia(ensName);
      if (!resolved) {
        await emitRemote({
          kind: 'agent.action',
          actor: 'alpha-trader',
          summary: `alpha-trader: ENS ${ensName} did not resolve on Sepolia (skipping)`,
          details: { ensName, network: 'sepolia' },
        });
        continue;
      }
      addr = resolved;
      ensDiscoveryCache.set(ensName, addr);
      await emitRemote({
        kind: 'agent.action',
        actor: 'alpha-trader',
        counterparty: ensName,
        summary: `alpha-trader discovered ${ensName} → ${addr.slice(0, 8)}… via Sepolia ENS`,
        details: { ensName, address: addr, network: 'sepolia', resolver: 'UniversalResolver' },
      });
    }
    out.push({ ensName, address: addr });
  }
  return out;
}

// ─── per-tick logic ────────────────────────────────────────────────────────

async function getSignal(analyst: DiscoveredAgent, walletId: string, marketId: string):
  Promise<{ signal: Signal; costUsdc: number; txHash?: string }> {
  // We call the address-based route. The server resolves address → label
  // server-side; the LOOP has no knowledge of the analyst's label — only
  // its ENS name and its Sepolia-resolved Arc address.
  const url = `${WALLET_BASE}/agent/by-address/${analyst.address}/signal?market=${encodeURIComponent(marketId)}`;
  const { body, costUsdc, txHash } = await fetchWithX402(url, {
    walletId,
    payerLabel: 'alpha-trader',
    maxUsdc: MAX_USDC_PER_TICK,
  });
  const { prediction } = body as { prediction: Signal };
  return { signal: prediction, costUsdc, txHash };
}

// Trades opened by the loop, awaiting "resolution". We keep this in-process
// since resolution is itself simulated.
const openTrades: OpenTrade[] = [];
let tickCount = 0;

async function tick(alphaAddress: `0x${string}`, alphaWalletId: string) {
  tickCount++;
  const market = MARKETS[Math.floor(Math.random() * MARKETS.length)]!;
  await emitRemote({
    kind: 'agent.action',
    actor: 'alpha-trader',
    summary: `alpha-trader picked market ${market}`,
    details: { market, tick: tickCount },
  });

  // 1. Discover analysts via Sepolia ENS (not local JSON).
  const analysts = await discoverAnalystsViaEns();
  if (analysts.length === 0) {
    console.log('  no analysts resolved via ENS this tick; skipping');
    return;
  }

  // 2. Pay each via x402 and collect signals.
  const results: Signal[] = [];
  let totalCost = 0;

  for (const analyst of analysts) {
    try {
      const { signal, costUsdc } = await getSignal(analyst, alphaWalletId, market);
      results.push(signal);
      totalCost += costUsdc;
    } catch (err) {
      console.error(`  [${analyst.ensName}] failed:`, (err as Error).message);
    }
  }

  if (results.length === 0) {
    console.log('  no signals collected this tick; skipping attestation');
    return;
  }

  // 3. Blend confidence-weighted.
  const w = results.reduce((s, r) => s + r.confidence, 0);
  const blendedFair = results.reduce((s, r) => s + r.fair_yes * r.confidence, 0) / w;
  const blendedConfidence = results.reduce((s, r) => s + r.confidence, 0) / results.length;

  const researchPayload = {
    market,
    fair_yes: Number(blendedFair.toFixed(4)),
    confidence: Number(blendedConfidence.toFixed(3)),
    inputs: results,
    blended_by: 'alpha-trader',
    ts: Date.now(),
  };
  const researchHash = '0x' + createHash('sha256')
    .update(JSON.stringify(researchPayload))
    .digest('hex');

  await emitRemote({
    kind: 'agent.action',
    actor: 'alpha-trader',
    summary: `alpha-trader blended ${results.length} signals → fair=${researchPayload.fair_yes} (paid $${totalCost.toFixed(3)} USDC)`,
    details: { market, fair: researchPayload.fair_yes, totalCostUsdc: totalCost, researchHash },
  });

  // 4. Anchor research attestation (Privy-signed by alpha-trader).
  try {
    const attest = await anchorResearchRemote({
      researchHash,
      ens: 'alpha-trader',
      marketId: market,
    });
    console.log(`  ✓ anchored research ${market} → ${attest.tx_hash}${attest.mock ? ' (mock)' : ''}`);
  } catch (err) {
    console.error('  research attestation failed:', (err as Error).message);
  }

  // 5. Decide whether to trade. Mock "market price" = 0.50 for the demo.
  //    Edge = |fair - market_price|. If above threshold, simulate a paper trade
  //    and anchor a trade attestation.
  const marketPrice = 0.50;
  const edge = Math.abs(researchPayload.fair_yes - marketPrice);
  if (edge >= EDGE_THRESHOLD) {
    const side: 'BUY' | 'SELL' = researchPayload.fair_yes > marketPrice ? 'BUY' : 'SELL';
    const sizeUsd = Number((0.50 + Math.random() * 1.50).toFixed(2)); // $0.50-$2.00 paper size
    const recId = randomUUID();
    try {
      const trade = await anchorTradeRemote({
        recId,
        ens: 'alpha-trader',
        user: alphaAddress,
        marketId: market,
        side,
        price: marketPrice,
        sizeUsd,
      });
      openTrades.push({ recId, marketId: market, side, price: marketPrice, sizeUsd, openedAt: Date.now() });
      await emitRemote({
        kind: 'attestation',
        actor: 'alpha-trader',
        summary: `alpha-trader opened paper ${side} $${sizeUsd.toFixed(2)} @ ${marketPrice.toFixed(2)} on ${market.slice(0, 18)}… (edge=${edge.toFixed(3)})`,
        details: {
          txHash: trade.tx_hash, recId, marketId: market, side, price: marketPrice,
          sizeUsd, edge, mock: trade.mock, explorer: trade.explorer_url,
        },
      });
      console.log(`  ✓ anchored trade ${recId.slice(0, 8)}… → ${trade.tx_hash}${trade.mock ? ' (mock)' : ''}`);
    } catch (err) {
      console.error('  trade attestation failed:', (err as Error).message);
    }
  } else {
    console.log(`  edge ${edge.toFixed(3)} < ${EDGE_THRESHOLD} threshold, no trade`);
  }

  // 6. Periodically settle the oldest open trade.
  if (tickCount % RESOLUTION_EVERY === 0 && openTrades.length > 0) {
    const trade = openTrades.shift()!;
    // Coin-flip outcome. PnL = +sizeUsd if we won, -sizeUsd if we lost.
    const won = Math.random() < 0.55; // mild positive bias for the demo
    const resolvedOutcome = won
      ? (trade.side === 'BUY' ? 'YES' : 'NO')
      : (trade.side === 'BUY' ? 'NO' : 'YES');
    const pnlUsd = won ? trade.sizeUsd : -trade.sizeUsd;
    try {
      const res = await anchorResolutionRemote({
        recId: trade.recId,
        resolvedOutcome,
        pnlUsd,
        ens: 'alpha-trader',
      });
      await emitRemote({
        kind: 'attestation',
        actor: 'alpha-trader',
        summary: `alpha-trader settled ${trade.marketId.slice(0, 18)}… → ${resolvedOutcome}, PnL ${pnlUsd >= 0 ? '+' : ''}$${pnlUsd.toFixed(2)}`,
        details: {
          txHash: res.tx_hash, recId: trade.recId, resolvedOutcome, pnlUsd,
          mock: res.mock, explorer: res.explorer_url,
        },
      });
      console.log(`  ✓ resolved trade ${trade.recId.slice(0, 8)}… → ${res.tx_hash}${res.mock ? ' (mock)' : ''}`);
    } catch (err) {
      console.error('  resolution attestation failed:', (err as Error).message);
    }
  }
}

async function main() {
  const alpha = findAgent('alpha-trader');
  if (!alpha) throw new Error('alpha-trader missing from var/agents.json — run `make provision-agents`');

  console.log(`autonomous loop: alpha-trader (${alpha.address})`);
  console.log(`  wallet service:  ${WALLET_BASE}`);
  console.log(`  tick interval:   ${TICK_SEC}s`);
  console.log(`  max spend/tick:  $${MAX_USDC_PER_TICK} USDC`);
  console.log(`  edge threshold:  ${EDGE_THRESHOLD}`);
  console.log(`  resolve every:   ${RESOLUTION_EVERY} ticks`);
  console.log(`  ENS parent:      ${ENS_PARENT} (resolved on Sepolia L1)`);
  console.log(`  analysts (ENS):  ${ANALYST_ENS_NAMES.join(', ')}`);
  console.log('');

  // Sequential tick loop. Wait for each tick to fully complete before
  // sleeping TICK_SEC and starting the next one. This makes the in-process
  // openTrades queue + tickCount deterministic (no overlapping ticks
  // racing on shared state) and keeps the activity feed in a sane order.
  // Tick budget is bounded by the analyst count + Arc receipt times; in
  // practice each tick takes ~10-25s depending on RPC.
  for (;;) {
    const t0 = Date.now();
    try {
      await tick(alpha.address, alpha.privyWalletId);
    } catch (e) {
      console.error('tick error:', e);
    }
    const elapsed = Date.now() - t0;
    const wait = Math.max(0, TICK_SEC * 1000 - elapsed);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
