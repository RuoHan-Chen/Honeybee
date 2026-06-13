/**
 * End-to-end smoke for agent rails:
 *
 *   A. Allowed: alpha-trader -> sports-analyst, 0.01 ARC on Arc testnet.
 *   B. Denied:  alpha-trader -> sports-analyst, 0.01 ETH on chainId=1.
 *      Should be rejected by the Privy policy engine (chain_id mismatch).
 *
 * Both calls go through the owner-signed Privy REST path, so we're also
 * exercising the authorization-signature flow.
 */
import 'dotenv/config';
import fs from 'node:fs';
import path from 'node:path';

import { sendTxFromPrivy } from '../execution/src/wallet/privy.js';

interface AgentsFile {
  agents: Array<{ label: string; address: `0x${string}`; privyWalletId: string }>;
}

async function main() {
  const file = JSON.parse(
    fs.readFileSync(path.resolve(process.cwd(), 'var/agents.json'), 'utf8'),
  ) as AgentsFile;

  const alpha   = file.agents.find((a) => a.label === 'alpha-trader');
  const sports  = file.agents.find((a) => a.label === 'sports-analyst');
  if (!alpha || !sports) throw new Error('expected alpha-trader + sports-analyst in agents.json');

  const valueWei = 10_000_000_000_000_000n; // 0.01

  console.log(`A) Allowed:  ${alpha.label} -> ${sports.label}  0.01 ARC on Arc`);
  try {
    const ok = await sendTxFromPrivy({
      walletId: alpha.privyWalletId,
      to: sports.address,
      valueWei,
    });
    console.log(`   PASS  tx=${ok.hash}  caip2=${ok.caip2}`);
  } catch (err) {
    console.log(`   UNEXPECTED FAIL: ${(err as Error).message}`);
    process.exit(1);
  }

  console.log('');
  console.log(`B) Denied:   ${alpha.label} -> ${sports.label}  0.6 ARC on Arc (over 0.5 cap)`);
  try {
    const bad = await sendTxFromPrivy({
      walletId: alpha.privyWalletId,
      to: sports.address,
      valueWei: 600_000_000_000_000_000n, // 0.6 > policy cap of 0.5
    });
    console.log(`   UNEXPECTED PASS: tx=${bad.hash}`);
    process.exit(1);
  } catch (err) {
    const msg = (err as Error).message;
    console.log(`   PASS  policy rejected: ${msg.slice(0, 240)}`);
  }

  console.log('');
  console.log(`C) Denied:   ${alpha.label} -> ${sports.label}  on chainId=1 (off-Arc)`);
  try {
    const bad = await sendTxFromPrivy({
      walletId: alpha.privyWalletId,
      to: sports.address,
      valueWei: 1n,
      chainId: 1,
    });
    console.log(`   UNEXPECTED PASS: tx=${bad.hash}`);
  } catch (err) {
    const msg = (err as Error).message;
    console.log(`   PASS  policy rejected: ${msg.slice(0, 240)}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
