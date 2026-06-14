/**
 * Kalshi live execution — RSA-PSS signed order submission.
 *
 * Auth: every authenticated request carries three headers —
 *   KALSHI-ACCESS-KEY        the API key id
 *   KALSHI-ACCESS-TIMESTAMP  unix time in MILLISECONDS
 *   KALSHI-ACCESS-SIGNATURE  base64( RSA-PSS-SHA256( `${tsMs}${METHOD}${path}` ) )
 * where `path` is the route WITHOUT query string, including the /trade-api/v2 prefix.
 *
 * Defaults to the DEMO sandbox so fills cost no real money. Point KALSHI_API_URL
 * at production only when you mean it. Uses only Node built-ins (node:crypto +
 * global fetch) — no third-party deps.
 */
import { readFileSync } from 'node:fs';
import crypto from 'node:crypto';

import type { Fill, OrderIn } from '../paper.js';
import type { KalshiCreds, RecommendationLite, BrokerFill } from '../broker/types.js';

const DEMO_BASE = 'https://external-api.demo.kalshi.co/trade-api/v2';

function baseUrl(): string {
  return (process.env.KALSHI_API_URL ?? DEMO_BASE).replace(/\/$/, '');
}

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

/** Build the three signed headers for a Kalshi authenticated request. */
export function signKalshiHeaders(
  apiKeyId: string,
  privateKeyPem: string,
  method: string,
  signingPath: string,
  tsMs: number,
): Record<string, string> {
  const message = `${tsMs}${method.toUpperCase()}${signingPath}`;
  const signature = crypto
    .sign('sha256', Buffer.from(message, 'utf8'), {
      key: privateKeyPem,
      padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
      saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST, // = digest length (32)
    })
    .toString('base64');
  return {
    'KALSHI-ACCESS-KEY': apiKeyId,
    'KALSHI-ACCESS-SIGNATURE': signature,
    'KALSHI-ACCESS-TIMESTAMP': String(tsMs),
    'Content-Type': 'application/json',
  };
}

async function kalshiFetch(
  creds: KalshiCreds,
  method: 'GET' | 'POST' | 'DELETE',
  route: string,
  body?: unknown,
): Promise<any> {
  const url = baseUrl() + route;
  const signingPath = new URL(url).pathname; // e.g. /trade-api/v2/portfolio/orders
  const headers = signKalshiHeaders(creds.apiKeyId, creds.privateKeyPem, method, signingPath, Date.now());
  const res = await fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`kalshi ${method} ${route} -> ${res.status}: ${text.slice(0, 300)}`);
  }
  return text ? JSON.parse(text) : {};
}

/** Map a recommendation to a Kalshi order body and submit it. */
async function placeOrder(
  creds: KalshiCreds,
  args: { ticker: string; outcome: string; side: 'BUY' | 'SELL'; price: number; sizeUsd: number; maxSlippageBps: number; clientOrderId: string },
): Promise<{ order: any; price: number; count: number }> {
  const action = args.side === 'BUY' ? 'buy' : 'sell';
  const yesNo = args.outcome.toUpperCase() === 'YES' ? 'yes' : 'no';
  // Marketable limit: cross the spread by the slippage budget so an IOC can fill.
  const slip = args.maxSlippageBps / 10_000;
  const px = clamp(args.price + (action === 'buy' ? slip : -slip), 0.01, 0.99);
  const count = Math.max(1, Math.floor(args.sizeUsd / Math.max(px, 0.01)));
  const priceField = yesNo === 'yes' ? 'yes_price_dollars' : 'no_price_dollars';

  const body: Record<string, unknown> = {
    ticker: args.ticker,
    action,
    side: yesNo,
    count,
    type: 'limit',
    [priceField]: px.toFixed(2),
    time_in_force: 'immediate_or_cancel', // marketable; cancels any unfilled remainder
    client_order_id: args.clientOrderId,
  };
  const resp = await kalshiFetch(creds, 'POST', '/portfolio/orders', body);
  return { order: resp.order ?? {}, price: px, count };
}

function num(x: unknown, dflt = 0): number {
  const v = typeof x === 'string' ? parseFloat(x) : (x as number);
  return Number.isFinite(v) ? v : dflt;
}

/** Broker path — submit using the USER'S Kalshi API key. */
export async function submitKalshiAsUser(
  creds: KalshiCreds,
  rec: RecommendationLite,
  maxSlippageBps: number,
): Promise<BrokerFill> {
  const { order, price, count } = await placeOrder(creds, {
    ticker: rec.market_id,
    outcome: rec.outcome,
    side: rec.side,
    price: rec.market_price,
    sizeUsd: rec.suggested_size_usd,
    maxSlippageBps,
    clientOrderId: rec.rec_id,
  });
  const filledCount = num(order.fill_count_fp, 0);
  const filledUsd = num(order.taker_fill_cost_dollars, filledCount * price);
  const avg = filledCount > 0 ? filledUsd / filledCount : price;
  return {
    rec_id: rec.rec_id,
    venue: 'kalshi',
    market_id: rec.market_id,
    outcome: rec.outcome,
    side: rec.side,
    avg_price: Number(avg.toFixed(4)),
    filled_usd: Number(filledUsd.toFixed(2)),
    broker_ref: String(order.order_id ?? 'kalshi-' + rec.rec_id.slice(0, 8)),
  };
}

/** Agent path (/submit) — submit using env-configured API key + key file. */
export async function submitKalshi(order: OrderIn): Promise<Fill> {
  const apiKeyId = process.env.KALSHI_API_KEY_ID;
  const keyPath = process.env.KALSHI_PRIVATE_KEY_PATH;
  if (!apiKeyId || !keyPath) {
    throw new Error('Kalshi live submission needs KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH.');
  }
  const creds: KalshiCreds = { apiKeyId, privateKeyPem: readFileSync(keyPath, 'utf8') };
  const { order: resp, price, count } = await placeOrder(creds, {
    ticker: order.market_id,
    outcome: order.outcome,
    side: order.side,
    price: order.limit_price,
    sizeUsd: order.size_usd,
    maxSlippageBps: order.max_slippage_bps,
    clientOrderId: order.idempotency_key || 'agent-' + order.market_id,
  });
  const filledCount = num(resp.fill_count_fp, 0);
  const filledUsd = num(resp.taker_fill_cost_dollars, filledCount * price);
  return {
    venue: 'kalshi',
    market_id: order.market_id,
    outcome: order.outcome,
    side: order.side,
    avg_price: Number((filledCount > 0 ? filledUsd / filledCount : price).toFixed(4)),
    filled_usd: Number(filledUsd.toFixed(2)),
    fee_usd: 0,
    paper: false,
  };
}
