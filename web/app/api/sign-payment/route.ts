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
