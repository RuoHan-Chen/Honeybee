/**
 * Autonomous trading-agent loop.
 *
 * Runs as `alpha-trader`. Every TICK_SEC, it:
 *
 *   1. Picks a market id (rotating through a tiny built-in list — replace with
 *      a real venue feed when wiring to production).
 *   2. Calls /agent/sports-analyst/signal     (gets 402 → pays $0.005 USDC → retries)
 *   3. Calls /agent/politics-analyst/signal   (gets 402 → pays $0.003 USDC → retries)
 *   4. Blends the two fair prices.
 *   5. Anchors a research attestation on Arc, tagged with alpha-trader's ENS node.
 *
 * Every step emits an activity event the UI ticker can render. No human is in
 * the loop — kill the script with Ctrl-C to stop.
 */
import 'dotenv/config';
import { fetchWithX402 } from '../execution/src/x402/client.js';
import { findAgent, loadRoster } from '../execution/src/agents/registry.js';
import { createHash } from 'node:crypto';

const WALLET_BASE = process.env.WALLET_SERVICE_URL ?? 'http://127.0.0.1:8787';
const TICK_SEC = Number(process.env.AGENT_LOOP_TICK_SEC ?? 30);
const MAX_USDC_PER_TICK = Number(process.env.AGENT_LOOP_MAX_USDC ?? 0.02);

/**
 * Publish an activity event to the wallet service's in-process bus. We do this
 * over HTTP (not via the local EventEmitter) so the UI's SSE stream sees
 * everything the autonomous loop does, including market-pick / blend / anchor.
 */
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

/**
 * Anchor a research attestation via the wallet service so it lands on the
 * same Arc signer and the resulting "attestation" event hits the SSE bus.
 */
async function anchorResearchRemote(input: { researchHash: string; ens: string; marketId: string }):
  Promise<{ tx_hash: string; mock: boolean; explorer_url: string | null }> {
  const r = await fetch(`${WALLET_BASE}/attest/research`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(`attest/research ${r.status}: ${await r.text()}`);
  return r.json();
}

// Demo markets — replace with a venue list call when wiring to prod.
const MARKETS = [
  'will-arsenal-beat-chelsea-2026-07-04',
  'us-cpi-yoy-jun-2026-above-3pct',
  'btc-above-100k-by-2026-q4',
  'fed-cuts-25bps-by-aug-2026',
];

interface Signal { fair_yes: number; confidence: number; agent: string; marketId: string }

async function getSignal(analystLabel: string, walletId: string, marketId: string): Promise<{ signal: Signal; costUsdc: number; txHash?: string }> {
  const url = `${WALLET_BASE}/agent/${analystLabel}/signal?market=${encodeURIComponent(marketId)}`;
  const { body, costUsdc, txHash } = await fetchWithX402(url, {
    walletId,
    payerLabel: 'alpha-trader',
    maxUsdc: MAX_USDC_PER_TICK,
  });
  const { prediction } = body as { prediction: Signal };
  return { signal: prediction, costUsdc, txHash };
}

async function tick(roster: ReturnType<typeof loadRoster>, alphaWalletId: string) {
  const market = MARKETS[Math.floor(Math.random() * MARKETS.length)]!;
  await emitRemote({
    kind: 'agent.action',
    actor: 'alpha-trader',
    summary: `alpha-trader picked market ${market}`,
    details: { market },
  });

  const results: Signal[] = [];
  let totalCost = 0;

  for (const analyst of ['sports-analyst', 'politics-analyst']) {
    try {
      const { signal, costUsdc } = await getSignal(analyst, alphaWalletId, market);
      results.push(signal);
      totalCost += costUsdc;
    } catch (err) {
      console.error(`  [${analyst}] failed:`, (err as Error).message);
    }
  }

  if (results.length === 0) {
    console.log('  no signals collected this tick; skipping attestation');
    return;
  }

  // Blend: confidence-weighted mean of fair_yes.
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

  // The wallet svc emits the "attestation" activity event itself, so we just
  // fire-and-log here.
  try {
    const attest = await anchorResearchRemote({
      researchHash,
      ens: 'alpha-trader',
      marketId: market,
    });
    console.log(`  ✓ anchored research ${market} → ${attest.tx_hash}${attest.mock ? ' (mock)' : ''}`);
  } catch (err) {
    console.error('  attestation failed:', (err as Error).message);
  }
}

async function main() {
  const roster = loadRoster();
  const alpha = findAgent('alpha-trader');
  if (!alpha) throw new Error('alpha-trader missing from var/agents.json — run `make provision-agents`');

  console.log(`autonomous loop: alpha-trader (${alpha.address})`);
  console.log(`  wallet service: ${WALLET_BASE}`);
  console.log(`  tick interval:  ${TICK_SEC}s`);
  console.log(`  max spend/tick: $${MAX_USDC_PER_TICK} USDC`);
  console.log(`  analysts:       ${roster.filter((a) => a.role === 'research').map((a) => a.label).join(', ')}`);
  console.log('');

  // First tick immediately, then on interval.
  await tick(roster, alpha.privyWalletId).catch((e) => console.error('tick error:', e));
  setInterval(() => {
    tick(roster, alpha.privyWalletId).catch((e) => console.error('tick error:', e));
  }, TICK_SEC * 1000);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
