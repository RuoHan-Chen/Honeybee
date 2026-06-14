/**
 * Blink deposit signer — POST /api/sign-payment
 *
 * Per Blink's integration guide: build the payload, base64url-encode the JSON,
 * sign the base64url STRING (not the raw JSON — their #1 gotcha) with the
 * merchant's ECDSA P-256 key, and return { merchantId, payload, signature }.
 *
 * Node runtime only — node:crypto + a PEM key; the edge runtime can't sign.
 * The private key is read from the server env and never leaves the backend.
 */
import { createSign, randomUUID } from 'node:crypto';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MERCHANT_ID = process.env.BLINK_MERCHANT_ID ?? '';
const PRIVATE_KEY_PEM = process.env.BLINK_MERCHANT_PRIVATE_KEY ?? '';

// Blink-supported destination (chainId -> token addresses, lowercased). Blink's
// guide recommends allowlisting supported combos so you never sign an
// unroutable deposit. For production, query Blink's Chains API instead of pinning.
const SUPPORTED: Record<number, Set<string>> = {
  1: new Set(['0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48']),                       // Ethereum USDC
  56: new Set(['0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d']),                      // BSC USDC
  137: new Set([
    '0x3c499c542cef5e3811e1192ce70d8cc03d5c3359',                                   // Polygon USDC (native)
    '0x2791bca1f2de4661ed88a30c99a7a9449aa84174',                                   // Polygon USDC.e (Polymarket)
    '0xc2132d05d31c914a87c6611c10748aeb04b58e8f',                                   // Polygon USDT
  ]),
  8453: new Set(['0x833589fcd6edb6e08f4c7c32d4f71b54bda02913']),                    // Base USDC
  42161: new Set(['0xaf88d065e77c8cc2239327c5edb3a432268e5831']),                   // Arbitrum USDC
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}

export async function POST(req: Request): Promise<Response> {
  if (!MERCHANT_ID || !PRIVATE_KEY_PEM) {
    return json({ error: 'Blink not configured: set BLINK_MERCHANT_ID + BLINK_MERCHANT_PRIVATE_KEY' }, 500);
  }

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ error: 'invalid JSON body' }, 400);
  }

  const { amount, chainId, address, token, callbackScheme = null, version = 'v1' } = body as {
    amount?: number; chainId?: number; address?: string; token?: string;
    callbackScheme?: string | null; version?: string;
  };

  if (typeof amount !== 'number' || !Number.isFinite(amount) || amount <= 0) {
    return json({ error: 'Invalid amount' }, 400);
  }
  if (!Number.isInteger(chainId) || (chainId as number) <= 0) {
    return json({ error: 'Invalid chainId' }, 400);
  }
  if (typeof address !== 'string' || !/^0x[a-fA-F0-9]{40}$/.test(address)) {
    return json({ error: 'Invalid address' }, 400);
  }
  if (typeof token !== 'string' || !/^0x[a-fA-F0-9]{40}$/.test(token)) {
    return json({ error: 'Invalid token' }, 400);
  }
  const supported = SUPPORTED[chainId as number];
  if (!supported || !supported.has(token.toLowerCase())) {
    return json({ error: `Unsupported (chainId ${chainId}, token ${token}) for Blink` }, 400);
  }

  const payloadObject = {
    amount,
    chainId,
    address,
    token,
    idempotencyKey: randomUUID(),       // fresh per request (Blink dedupes on it)
    callbackScheme,
    signatureTimestamp: new Date().toISOString(),  // Blink enforces <15min age
    version,
  };

  // base64url-encode the JSON, then sign THAT string (not the JSON).
  const payload = Buffer.from(JSON.stringify(payloadObject), 'utf8').toString('base64url');
  const signature = createSign('SHA256').update(payload).end().sign(PRIVATE_KEY_PEM).toString('base64url');

  return json({
    merchantId: MERCHANT_ID,
    payload,
    signature,
    preview: { amount, chainId, address, token },
  });
}
