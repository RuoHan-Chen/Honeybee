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
import { readFileSync } from 'node:fs';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MERCHANT_ID = process.env.BLINK_MERCHANT_ID ?? '';

/**
 * Load the merchant PEM — from env contents (handles \n-escaped single-line
 * values) or a file path (BLINK_MERCHANT_PRIVATE_KEY_PATH). Never from the request.
 */
function loadPrivateKey(): string {
  const inline = process.env.BLINK_MERCHANT_PRIVATE_KEY;
  if (inline && inline.includes('BEGIN')) return inline.replace(/\\n/g, '\n');
  const path = process.env.BLINK_MERCHANT_PRIVATE_KEY_PATH;
  if (path) {
    try {
      return readFileSync(path, 'utf8');
    } catch {
      /* fall through to empty */
    }
  }
  return '';
}

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

// Blink testnet sandbox routes (Base Sepolia + Sepolia USDC). Relay's mainnet
// /chains doesn't list these, so the sandbox combos are allowlisted explicitly.
const SANDBOX_SUPPORTED: Record<number, Set<string>> = {
  84532: new Set(['0x036cbd53842c5426634e7929541ec2318f3dcf7e']),     // Base Sepolia USDC
  11155111: new Set(['0x1c7d4b196cb0c7b01d743fbc6116a902379c7238']),  // Sepolia USDC
};

// Authoritative support comes from Blink's routing layer (Relay) Chains API at
// runtime; the static table above is only used if that endpoint is unreachable.
const RELAY_CHAINS_URL = 'https://api.relay.link/chains';
const CHAINS_TTL_MS = 10 * 60_000;
let chainsCache: { ts: number; chains: unknown[] } | null = null;

async function getChains(): Promise<any[] | null> {
  if (chainsCache && Date.now() - chainsCache.ts < CHAINS_TTL_MS) return chainsCache.chains as any[];
  try {
    const r = await fetch(RELAY_CHAINS_URL, { cache: 'no-store' });
    if (!r.ok) return null;
    const data = await r.json();
    const chains = Array.isArray(data?.chains) ? data.chains : Array.isArray(data) ? data : null;
    if (chains) chainsCache = { ts: Date.now(), chains };
    return chains;
  } catch {
    return null;
  }
}

/** Validate (chainId, token) against Relay's live routing catalog. */
async function isSupported(chainId: number, token: string): Promise<boolean> {
  const tokenLc = token.toLowerCase();
  if (SANDBOX_SUPPORTED[chainId]?.has(tokenLc)) return true;  // testnet sandbox combos
  const chains = await getChains();
  if (chains) {
    const chain = chains.find((c: any) => c.id === chainId);
    if (!chain) return false;
    const listed = [chain.currency, ...(chain.erc20Currencies ?? [])].filter(Boolean);
    const entry = listed.find((t: any) => (t.address ?? '').toLowerCase() === tokenLc);
    if (entry) return entry.supportsBridging === true;   // listed token: must be bridgeable
    return chain.tokenSupport === 'All';                 // unlisted on an open chain: routed by liquidity
  }
  return SUPPORTED[chainId]?.has(tokenLc) ?? false;       // Relay unreachable → static fallback
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}

export async function POST(req: Request): Promise<Response> {
  const PRIVATE_KEY_PEM = loadPrivateKey();
  if (!MERCHANT_ID || !PRIVATE_KEY_PEM) {
    return json({ error: 'Blink not configured: set BLINK_MERCHANT_ID + BLINK_MERCHANT_PRIVATE_KEY (or _PATH)' }, 500);
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
  if (!(await isSupported(chainId as number, token))) {
    return json({ error: `Unsupported (chainId ${chainId}, token ${token}) — not in Blink/Relay routing catalog` }, 400);
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
