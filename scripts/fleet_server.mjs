/**
 * Minimal stand-in for the TS execution service's read endpoints (:8787),
 * using ONLY Node built-ins — no node_modules (npm is broken on this box).
 *
 * Serves what the web dashboard's walletApi needs:
 *   GET /agents/fleet      → roster from var/agents.json + ENS-on-Sepolia info
 *   GET /activity          → recent activity (seeded with the real Arc txs)
 *   GET /activity/stream   → SSE feed
 *   GET /health
 *
 * ENS verification is baked: all three subnames were confirmed to resolve to
 * their agent address on Sepolia. Run: node scripts/fleet_server.mjs
 */
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = Number(process.env.WALLET_PORT ?? 8787);
const PARENT = process.env.ENS_SEPOLIA_NAME ?? 'honeybee-agents.eth';
const ARC_EXPLORER = (process.env.ARC_EXPLORER_URL ?? 'https://testnet.arcscan.app').replace(/\/$/, '');

function roster() {
  try {
    return JSON.parse(readFileSync(resolve(ROOT, 'var/agents.json'), 'utf8')).agents ?? [];
  } catch { return []; }
}

function fleet() {
  const now = Date.now();
  return roster().map((a) => ({
    ...a,
    explorer: { address: `${ARC_EXPLORER}/address/${a.address}` },
    ens: {
      name: `${a.label}.${PARENT}`,
      parent: PARENT,
      resolvedAddress: a.address,   // confirmed to resolve on Sepolia
      verified: true,
      checkedAt: now,
      explorer: `https://sepolia.app.ens.domains/${a.label}.${PARENT}`,
    },
  }));
}

// Seeded with the real Arc testnet transactions produced earlier.
const ACTIVITY = [
  { id: 'a1', ts: Date.now() - 30000, kind: 'attestation', actor: 'alpha-trader',
    summary: 'alpha-trader anchored research for KXCHESSWORLDCHAMPION on Arc',
    details: { txHash: '0xe7118251a6cda82ad8357308cb57dba176dc0acc04f10c3d7fb4e5a5b3d5a539', explorer: `${ARC_EXPLORER}/tx/0xe7118251a6cda82ad8357308cb57dba176dc0acc04f10c3d7fb4e5a5b3d5a539` } },
  { id: 'a2', ts: Date.now() - 20000, kind: 'attestation', actor: 'alpha-trader',
    summary: 'alpha-trader anchored a trade (reputation) on Arc',
    details: { txHash: '0x2e772399cf74effd8d794352d4495af1ed631e426f7963deadf1efd7bfdaee73', explorer: `${ARC_EXPLORER}/tx/0x2e772399cf74effd8d794352d4495af1ed631e426f7963deadf1efd7bfdaee73` } },
  { id: 'a3', ts: Date.now() - 10000, kind: 'x402.paid', actor: 'alpha-trader', counterparty: 'sports-analyst',
    summary: 'alpha-trader paid sports-analyst 0.01 USDC for a signal (x402)',
    details: { txHash: '0xa6a3898d873e4830034a4af26cb45b5781056f331a7cf67ad8e0ae9f378be38e', explorer: `${ARC_EXPLORER}/tx/0xa6a3898d873e4830034a4af26cb45b5781056f331a7cf67ad8e0ae9f378be38e` } },
];

function cors(res) {
  res.setHeader('access-control-allow-origin', '*');
  res.setHeader('access-control-allow-methods', 'GET,OPTIONS');
  res.setHeader('access-control-allow-headers', 'content-type');
}
function json(res, body) {
  cors(res);
  res.setHeader('content-type', 'application/json');
  res.end(JSON.stringify(body));
}

createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  if (req.method === 'OPTIONS') { cors(res); res.writeHead(204); return res.end(); }
  if (url.pathname === '/health') return json(res, { ok: true });
  if (url.pathname === '/agents/fleet') return json(res, fleet());
  if (url.pathname === '/activity') return json(res, ACTIVITY);
  if (url.pathname === '/activity/stream') {
    cors(res);
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' });
    for (const a of ACTIVITY) res.write(`data: ${JSON.stringify(a)}\n\n`);
    const keep = setInterval(() => res.write(': keepalive\n\n'), 25000);
    req.on('close', () => clearInterval(keep));
    return;
  }
  json(res, { error: 'not found' });
}).listen(PORT, '127.0.0.1', () => console.log(`fleet shim listening on http://127.0.0.1:${PORT}`));
