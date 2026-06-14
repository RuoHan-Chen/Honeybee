/**
 * Honeybee wallet + execution service.
 *
 * Receives orders from the Python orchestrator and either:
 *   - paper-fills them against a live orderbook snapshot (DRY_RUN), or
 *   - signs and submits to the appropriate venue using a Privy-backed wallet.
 *
 * For the MVP we ship the paper-fill path end-to-end and stub the live
 * signing paths so they're ready to wire up when keys arrive.
 */
import 'dotenv/config';
import Fastify from 'fastify';

import { paperFill } from './paper.js';
import { submitPolymarket } from './venues/polymarket.js';
import { submitKalshi } from './venues/kalshi.js';
import { resolveEns, resolveEnsOnSepolia } from './wallet/ens.js';
import { createAgentWallet, getAgentWallet, getPrivyWalletAddress, sendTxFromPrivy } from './wallet/privy.js';
import { anchorResearch, anchorResolution, anchorTrade } from './chain/attestation.js';
import { getBroker } from './broker/index.js';
import { findAgent, loadRoster } from './agents/registry.js';
import { requireUsdcPayment } from './x402/server.js';
import { events as activityEvents, recentActivity, emitActivity } from './x402/events.js';
import { usdcToBaseUnits } from './chain/usdc.js';
import { createHash, randomUUID } from 'node:crypto';

const PORT = Number(process.env.WALLET_PORT ?? 8787);
const DRY_RUN = (process.env.DRY_RUN ?? 'true').toLowerCase() !== 'false';

const app = Fastify({ logger: { level: process.env.LOG_LEVEL?.toLowerCase() ?? 'info' } });

// CORS so the Next.js frontend (:3000) can call us.
app.addHook('onSend', async (_req, reply) => {
  reply.header('access-control-allow-origin', '*');
  reply.header('access-control-allow-methods', 'GET,POST,OPTIONS');
  reply.header('access-control-allow-headers', 'content-type');
});
app.options('/*', async (_req, reply) => reply.code(204).send());

interface OrderIn {
  venue: string;
  market_id: string;
  outcome: string;
  side: 'BUY' | 'SELL';
  limit_price: number;
  size_usd: number;
  max_slippage_bps: number;
  dry_run: boolean;
  idempotency_key: string;
}

app.get('/health', async () => ({
  ok: true,
  dry_run: DRY_RUN,
  ens: process.env.ENS_NAME || null,
  wallet: await getPrivyWalletAddress().catch(() => null),
}));

app.get('/identity', async () => {
  const ens = process.env.ENS_NAME || null;
  const address = ens ? await resolveEns(ens).catch(() => null) : null;
  return { ens, address };
});

// Mint a new Privy-managed agent wallet on Arc.
app.post('/wallet/create', async (req) => {
  const body = (req.body ?? {}) as { ownerKeyQuorumId?: string; policyIds?: string[] };
  return createAgentWallet(body);
});

app.get('/wallet/:id', async (req) => {
  const { id } = req.params as { id: string };
  return (await getAgentWallet(id)) ?? { error: 'not found' };
});

// Agent → agent native payment on Arc. Caller passes the FROM wallet id
// (Privy id) and a TO that is either:
//   - 0xaddress
//   - ENS-shaped label ("sports-analyst") — resolved via var/agents.json
// Per-tx value cap is enforced server-side by the wallet's Privy policy.
app.post('/agent/pay', async (req, reply) => {
  const body = req.body as {
    fromWalletId: string;
    to: string;
    valueWei: string;
    memo?: string;
  };
  if (!body?.fromWalletId || !body?.to || !body?.valueWei) {
    reply.code(400);
    return { error: 'fromWalletId, to, valueWei required' };
  }
  let toAddress: `0x${string}`;
  let toLabel: string | undefined;
  if (body.to.startsWith('0x') && body.to.length === 42) {
    toAddress = body.to as `0x${string}`;
  } else {
    const resolved = findAgent(body.to);
    if (!resolved) {
      reply.code(400);
      return { error: `unknown agent label: ${body.to}` };
    }
    toAddress = resolved.address;
    toLabel = resolved.label;
  }
  try {
    const out = await sendTxFromPrivy({
      walletId: body.fromWalletId,
      to: toAddress,
      valueWei: BigInt(body.valueWei),
    });
    const fromAgent = loadRoster().find((a) => a.privyWalletId === body.fromWalletId);
    emitActivity({
      kind: 'agent.action',
      actor: fromAgent?.label,
      counterparty: toLabel ?? toAddress,
      summary: `${fromAgent?.label ?? body.fromWalletId} paid ${toLabel ?? toAddress.slice(0, 8) + '…'} (native)`,
      details: { txHash: out.hash, memo: body.memo ?? null },
    });
    return { ...out, memo: body.memo ?? null, resolved: { to: toAddress, label: toLabel ?? null } };
  } catch (err: any) {
    app.log.error({ err }, 'agent/pay failed');
    reply.code(502);
    return { error: err?.message ?? String(err) };
  }
});

// ─── Agent fleet + activity ───────────────────────────────────────────────

// Cache ENS-on-Sepolia verification so we don't hammer the public RPC on
// every fleet fetch. Verification is "does <label>.<parent>.eth resolve to
// this agent's Arc address on Sepolia L1?".
const ENS_SEPOLIA_PARENT = process.env.ENS_SEPOLIA_NAME ?? null;
interface EnsVerification {
  name: string;
  parent: string;
  resolvedAddress: `0x${string}` | null;
  verified: boolean;
  checkedAt: number;
  explorer: string;
}
const ensCache = new Map<string, EnsVerification>();
const ENS_CACHE_TTL_MS = 60_000;

async function ensInfoFor(label: string, agentAddress: `0x${string}`): Promise<EnsVerification | null> {
  if (!ENS_SEPOLIA_PARENT) return null;
  const name = `${label}.${ENS_SEPOLIA_PARENT}`;
  const cached = ensCache.get(name);
  if (cached && Date.now() - cached.checkedAt < ENS_CACHE_TTL_MS) return cached;
  const resolved = await resolveEnsOnSepolia(name);
  const info: EnsVerification = {
    name,
    parent: ENS_SEPOLIA_PARENT,
    resolvedAddress: resolved,
    verified: !!resolved && resolved.toLowerCase() === agentAddress.toLowerCase(),
    checkedAt: Date.now(),
    explorer: `https://sepolia.app.ens.domains/${name}`,
  };
  ensCache.set(name, info);
  return info;
}

app.get('/agents/fleet', async () => {
  const roster = loadRoster();
  // Resolve ENS info in parallel. Failures are swallowed — UI just won't
  // show the verified badge for that agent.
  const enriched = await Promise.all(roster.map(async (a) => {
    const ens = await ensInfoFor(a.label, a.address).catch(() => null);
    return { ...a, ens };
  }));
  return enriched;
});

app.get('/activity', async () => recentActivity(100));

// POST /activity — publish an event into the in-process bus. Used by
// out-of-process agents (e.g. scripts/agent_loop.ts) so the SSE stream
// stays the single source of truth for the UI.
app.post('/activity', async (req, reply) => {
  const body = req.body as {
    kind: 'x402.required' | 'x402.paid' | 'x402.verified' | 'attestation' | 'agent.action';
    actor?: string;
    counterparty?: string;
    summary: string;
    details?: Record<string, unknown>;
  };
  if (!body?.kind || !body?.summary) {
    reply.code(400);
    return { error: 'kind and summary required' };
  }
  emitActivity(body);
  return { ok: true };
});

// Server-Sent Events feed for the live activity ticker.
app.get('/activity/stream', async (_req, reply) => {
  reply.raw.writeHead(200, {
    'content-type': 'text/event-stream',
    'cache-control': 'no-cache, no-transform',
    'connection': 'keep-alive',
    'access-control-allow-origin': '*',
  });
  // Prime with the buffer so a freshly-loaded UI isn't blank.
  for (const a of recentActivity(50).reverse()) {
    reply.raw.write(`data: ${JSON.stringify(a)}\n\n`);
  }
  const send = (a: unknown) => reply.raw.write(`data: ${JSON.stringify(a)}\n\n`);
  activityEvents.on('activity', send);
  reply.raw.on('close', () => activityEvents.off('activity', send));
});

// ─── x402-paid signal endpoint ────────────────────────────────────────────
// GET /agent/:label/signal?market=<id>
//   - 402 Payment Required (USDC on Arc) on first hit
//   - 200 with a signed prediction once payment is verified
//
// The "prediction" is a deterministic mock (seeded by agent + market) so the
// demo is reproducible without burning LLM credits, but the path is real:
// real USDC tx, real on-chain verification, real Privy-signed retry.
const SIGNAL_PRICE_USDC: Record<string, number> = {
  'sports-analyst': 0.005,
  'politics-analyst': 0.003,
  // Anything not listed defaults to 0.002 — alpha-trader doesn't sell signals.
};

function mockPrediction(agentLabel: string, marketId: string) {
  const seed = createHash('sha256').update(`${agentLabel}:${marketId}`).digest();
  // Fair price in [0.10, 0.90].
  const fair = 0.10 + (seed.readUInt32BE(0) / 0xffffffff) * 0.80;
  const confidence = 0.50 + (seed.readUInt32BE(4) / 0xffffffff) * 0.45;
  return {
    agent: agentLabel,
    marketId,
    fair_yes: Number(fair.toFixed(4)),
    confidence: Number(confidence.toFixed(3)),
    rationale: `${agentLabel} signal: deterministic mock based on market id (replace with real LLM in prod)`,
    ts: Date.now(),
  };
}

async function serveSignal(req: any, reply: any, agentRef: string) {
  const { market } = req.query as { market?: string };
  if (!market) {
    reply.code(400);
    return { error: 'market query param required' };
  }
  const agent = findAgent(agentRef);
  if (!agent) {
    reply.code(404);
    return { error: `unknown agent ${agentRef}` };
  }
  const price = SIGNAL_PRICE_USDC[agent.label] ?? 0.002;

  const gated = requireUsdcPayment({
    recipient: agent.address,
    recipientLabel: agent.label,
    priceBaseUnits: usdcToBaseUnits(price),
    description: `${agent.label} signal for market ${market}`,
    handler: ({ payer, txHash }) => {
      const prediction = mockPrediction(agent.label, market);
      const receiptId = randomUUID();
      emitActivity({
        kind: 'agent.action',
        actor: agent.label,
        counterparty: payer,
        summary: `${agent.label} served signal for ${market.slice(0, 12)}… (fair=${prediction.fair_yes})`,
        details: { receiptId, marketId: market, txHash, fair: prediction.fair_yes },
      });
      return {
        receipt: { id: receiptId, paid_tx: txHash, payer, price_usdc: price },
        prediction,
      };
    },
  });
  return gated(req, reply);
}

// Two routes, one handler:
//   /agent/:label/signal             — label-based (legacy, demo convenience)
//   /agent/by-address/:addr/signal   — address-based (ENS-discovery path; the
//                                      autonomous loop resolves a Sepolia ENS
//                                      subname to addr, then calls this route)
app.get('/agent/:label/signal', async (req, reply) => {
  const { label } = req.params as { label: string };
  return serveSignal(req, reply, label);
});

app.get('/agent/by-address/:addr/signal', async (req, reply) => {
  const { addr } = req.params as { addr: string };
  return serveSignal(req, reply, addr);
});

// ─── attestations (Arc testnet, mock fallback) ────────────────────────────
app.post('/attest/research', async (req, reply) => {
  const body = req.body as {
    researchHash: string;
    ens: string;
    marketId: string;
    /** Optional: explicit Privy walletId. If absent, resolves from `ens` via roster. */
    fromWalletId?: string;
  };
  // Auto-resolve walletId from the ENS label so callers don't have to plumb it.
  let fromWalletId = body.fromWalletId;
  if (!fromWalletId) {
    const agent = findAgent(body.ens);
    if (agent) fromWalletId = agent.privyWalletId;
  }
  try {
    const result = await anchorResearch({ ...body, fromWalletId });
    emitActivity({
      kind: 'attestation',
      actor: body.ens,
      summary: `${body.ens} anchored research for ${body.marketId} on Arc${result.mock ? ' (mock)' : ''}`,
      details: {
        txHash: result.tx_hash,
        marketId: body.marketId,
        researchHash: body.researchHash,
        mock: result.mock,
        explorer: result.explorer_url,
      },
    });
    return result;
  } catch (err: any) {
    app.log.error({ err }, 'attest/research failed');
    reply.code(500);
    return { error: err?.message ?? String(err) };
  }
});

app.post('/attest/trade', async (req) => {
  const body = req.body as {
    recId: string;
    ens?: string;
    user: `0x${string}`;
    marketId: string;
    side: 'BUY' | 'SELL';
    price: number;
    sizeUsd: number;
    fromWalletId?: string;
  };
  let fromWalletId = body.fromWalletId;
  if (!fromWalletId && body.ens) {
    const agent = findAgent(body.ens);
    if (agent) fromWalletId = agent.privyWalletId;
  }
  return anchorTrade({ ...body, fromWalletId });
});

app.post('/attest/resolution', async (req) => {
  const body = req.body as {
    recId: string;
    resolvedOutcome: string;
    pnlUsd: number;
    /** ENS label of the agent that originally anchored the trade. */
    ens?: string;
    fromWalletId?: string;
  };
  let fromWalletId = body.fromWalletId;
  if (!fromWalletId && body.ens) {
    const agent = findAgent(body.ens);
    if (agent) fromWalletId = agent.privyWalletId;
  }
  return anchorResolution({ ...body, fromWalletId });
});

// ─── broker: submit a trade USING USER'S credentials ──────────────────────
app.post('/broker/submit', async (req, reply) => {
  const body = req.body as {
    rec: import('./broker/types.js').RecommendationLite;
    creds: import('./broker/types.js').PolymarketCreds
         | import('./broker/types.js').KalshiCreds
         | import('./broker/types.js').GeminiCreds;
    maxSlippageBps?: number;
    user: `0x${string}`;
  };
  if (!body?.rec || !body?.creds) {
    reply.code(400);
    return { error: 'missing rec or creds' };
  }
  try {
    const broker = getBroker(body.rec.venue);
    const fill = await broker.submitAsUser({
      creds: body.creds,
      rec: body.rec,
      maxSlippageBps: body.maxSlippageBps ?? 200,
    });
    // Anchor trade attestation (fire-and-mirror).
    const attest = await anchorTrade({
      recId: fill.rec_id,
      user: body.user,
      marketId: fill.market_id,
      side: fill.side,
      price: fill.avg_price,
      sizeUsd: fill.filled_usd,
    });
    return { fill, attestation: attest };
  } catch (err: any) {
    app.log.error({ err }, 'broker submit failed');
    reply.code(502);
    return { error: err?.message ?? String(err) };
  }
});

app.post('/submit', async (req, reply) => {
  const body = req.body as { order: OrderIn; mid_price: number | null };
  const order = body?.order;
  if (!order) {
    reply.code(400);
    return { error: 'missing order' };
  }

  // Defense-in-depth: server-side circuit breaker.
  if (order.size_usd > Number(process.env.MAX_EXPOSURE_PER_MARKET_USD ?? 25)) {
    reply.code(403);
    return { error: 'server-side exposure cap exceeded' };
  }

  const isDry = DRY_RUN || order.dry_run;

  if (isDry) {
    const fill = paperFill(order, body.mid_price ?? order.limit_price);
    app.log.info({ fill }, 'paper fill');
    return { fill };
  }

  // Live path — route to venue-specific signer.
  try {
    let fill;
    switch (order.venue) {
      case 'polymarket':
        fill = await submitPolymarket(order);
        break;
      case 'kalshi':
        fill = await submitKalshi(order);
        break;
      default:
        reply.code(400);
        return { error: `live execution not implemented for venue ${order.venue}` };
    }
    return { fill };
  } catch (err: any) {
    app.log.error({ err }, 'live submit failed');
    reply.code(502);
    return { error: err?.message ?? String(err) };
  }
});

app.listen({ host: '127.0.0.1', port: PORT }).then(() => {
  app.log.info(`honeybee wallet service listening on :${PORT}  (DRY_RUN=${DRY_RUN})`);
});
