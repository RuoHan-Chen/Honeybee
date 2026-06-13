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
import { resolveEns } from './wallet/ens.js';
import { createAgentWallet, getAgentWallet, getPrivyWalletAddress } from './wallet/privy.js';
import { anchorResearch, anchorResolution, anchorTrade } from './chain/attestation.js';
import { getBroker } from './broker/index.js';

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
  const body = req.body as { label?: string };
  return createAgentWallet(body?.label);
});

app.get('/wallet/:id', async (req) => {
  const { id } = req.params as { id: string };
  return (await getAgentWallet(id)) ?? { error: 'not found' };
});

// ─── attestations (Arc testnet, mock fallback) ────────────────────────────
app.post('/attest/research', async (req) => {
  const body = req.body as { researchHash: string; ens: string; marketId: string };
  return anchorResearch(body);
});

app.post('/attest/trade', async (req) => {
  const body = req.body as { recId: string; user: `0x${string}`; marketId: string;
    side: 'BUY' | 'SELL'; price: number; sizeUsd: number };
  return anchorTrade(body);
});

app.post('/attest/resolution', async (req) => {
  const body = req.body as { recId: string; resolvedOutcome: string; pnlUsd: number };
  return anchorResolution(body);
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
