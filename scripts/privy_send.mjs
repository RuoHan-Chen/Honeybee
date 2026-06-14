/**
 * Minimal Privy-signed eth_sendTransaction on Arc — Node built-ins only.
 * Reads PRIVY_APP_ID / PRIVY_APP_SECRET / PRIVY_AUTH_PRIVATE_KEY / ARC_CHAIN_ID
 * and WALLET_ID from the environment; takes (to, data) as argv; prints tx hash.
 *
 * Inlines the Privy "direct" authorization-signature flow: P-256 / SHA-256 over
 * an RFC-8785 canonical payload, base64 DER → privy-authorization-signature.
 */
import crypto from 'node:crypto';

const [, , to, data] = process.argv;
const { PRIVY_APP_ID: APP_ID, PRIVY_APP_SECRET: APP_SECRET, PRIVY_AUTH_PRIVATE_KEY: AUTH_KEY, WALLET_ID } = process.env;
const CHAIN_ID = Number(process.env.ARC_CHAIN_ID);
const PRIVY_BASE = 'https://api.privy.io/v1';

function canon(v) {
  if (v === null) return 'null';
  if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
  if (typeof v === 'object') return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}';
  if (typeof v === 'number') return String(v);
  return JSON.stringify(v);
}
function loadKey(raw) {
  const b64 = raw.startsWith('wallet-auth:') ? raw.slice('wallet-auth:'.length) : raw;
  const pem = `-----BEGIN PRIVATE KEY-----\n${b64.match(/.{1,64}/g).join('\n')}\n-----END PRIVATE KEY-----\n`;
  return crypto.createPrivateKey({ key: pem, format: 'pem' });
}

const body = {
  method: 'eth_sendTransaction',
  caip2: `eip155:${CHAIN_ID}`,
  params: { transaction: { to, value: '0x0', chain_id: CHAIN_ID, ...(data && data !== '0x' ? { data } : {}) } },
};
const url = `${PRIVY_BASE}/wallets/${WALLET_ID}/rpc`;
const payload = { version: 1, method: 'POST', url, body, headers: { 'privy-app-id': APP_ID } };
const sig = crypto.sign('sha256', Buffer.from(canon(payload)), loadKey(AUTH_KEY)).toString('base64');

const res = await fetch(url, {
  method: 'POST',
  headers: {
    authorization: 'Basic ' + Buffer.from(`${APP_ID}:${APP_SECRET}`).toString('base64'),
    'privy-app-id': APP_ID,
    'content-type': 'application/json',
    'privy-authorization-signature': sig,
  },
  body: JSON.stringify(body),
});
const t = await res.text();
if (!res.ok) { console.error(`Privy ${res.status}: ${t}`); process.exit(1); }
console.log(JSON.parse(t).data.hash);
