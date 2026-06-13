/**
 * Privy authorization-signature helper.
 *
 * Implements the "direct" signing flow from
 *   https://docs.privy.io/controls/authorization-keys/using-owners/sign/direct-implementation
 *
 *   1. Build payload { version: 1, method, url, body, headers: { 'privy-app-id', ... } }
 *   2. JSON-canonicalize per RFC 8785
 *   3. ECDSA P-256 sign over the canonicalized bytes (SHA-256 implied by node 'sha256')
 *   4. base64 the DER signature
 *   5. Send as `privy-authorization-signature` header
 *
 * The private key is stored as base64 of a PKCS#8 DER blob (Privy's "wallet-auth:"
 * format with the prefix stripped). We accept either the raw key or the prefixed form.
 */
import crypto from 'node:crypto';
import canonicalize from 'canonicalize';

/** Generate a fresh P-256 keypair in Privy's expected base64-PKCS#8 format. */
export function generateP256Keypair(): { privateKey: string; publicKey: string } {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ec', {
    namedCurve: 'P-256',
    privateKeyEncoding: { type: 'pkcs8', format: 'der' },
    publicKeyEncoding:  { type: 'spki',  format: 'der' },
  });
  return {
    privateKey: privateKey.toString('base64'),
    publicKey:  publicKey.toString('base64'),
  };
}

function loadPrivateKey(raw: string): crypto.KeyObject {
  const b64 = raw.startsWith('wallet-auth:') ? raw.slice('wallet-auth:'.length) : raw;
  const pem = `-----BEGIN PRIVATE KEY-----\n${b64.match(/.{1,64}/g)!.join('\n')}\n-----END PRIVATE KEY-----\n`;
  return crypto.createPrivateKey({ key: pem, format: 'pem' });
}

export interface PrivySigPayload {
  version: 1;
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  url: string;
  body: unknown;
  headers: Record<string, string>;
}

/**
 * Sign a Privy API request and return the base64-encoded DER signature.
 * Caller must pass the EXACT body that will be sent on the wire (same JSON).
 */
export function signPrivyRequest(args: {
  privateKey: string;
  appId: string;
  method: PrivySigPayload['method'];
  url: string;
  body: unknown;
  idempotencyKey?: string;
  requestExpiryMs?: number;
}): { signature: string; headers: Record<string, string> } {
  const headers: Record<string, string> = { 'privy-app-id': args.appId };
  if (args.idempotencyKey) headers['privy-idempotency-key'] = args.idempotencyKey;
  if (args.requestExpiryMs) headers['privy-request-expiry'] = String(args.requestExpiryMs);

  const payload: PrivySigPayload = {
    version: 1,
    method: args.method,
    // Privy's spec says: "Should not include a trailing slash"
    url: args.url.replace(/\/$/, ''),
    body: args.body,
    headers,
  };

  const canonical = canonicalize(payload as unknown as object) as string;
  const key = loadPrivateKey(args.privateKey);
  const signature = crypto.sign('sha256', Buffer.from(canonical), key).toString('base64');

  return { signature, headers };
}
