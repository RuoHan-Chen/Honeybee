/**
 * One-shot Privy bootstrap.
 *
 *   1. Generate a P-256 authorization keypair.
 *   2. Register it as a `key_quorum` with threshold 1.
 *   3. Create a chain-locked policy:
 *        - Only Arc testnet (chain_id 5042002)
 *        - eth_sendTransaction value <= 0.5 ARC per tx
 *        - eth_signTransaction same restriction
 *        - eth_signTypedData_v4 allowed (we'll lock down later if needed)
 *
 *   4. Append PRIVY_AUTH_PRIVATE_KEY / PRIVY_AUTH_PUBLIC_KEY /
 *      PRIVY_OWNER_KEY_QUORUM_ID / PRIVY_POLICY_ID to .env so subsequent
 *      tooling picks them up.
 *
 * Idempotency: re-running creates *new* resources. We refuse to overwrite if
 * the env keys are already set, unless `--force` is passed.
 */
import 'dotenv/config';
import fs from 'node:fs';
import path from 'node:path';

import {
  generateP256Keypair,
} from '../execution/src/wallet/privy_sign.js';
import {
  createKeyQuorum,
  createPolicy,
  type PolicyRule,
} from '../execution/src/wallet/privy.js';

const ARC_CHAIN_ID = Number(process.env.ARC_CHAIN_ID ?? 5042002);
const ENV_PATH = path.resolve(process.cwd(), '.env');

// 0.5 ARC in wei.
const MAX_TX_VALUE_WEI = 500_000_000_000_000_000n;

function readEnv(): Record<string, string> {
  if (!fs.existsSync(ENV_PATH)) return {};
  const out: Record<string, string> = {};
  for (const line of fs.readFileSync(ENV_PATH, 'utf8').split('\n')) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (m) out[m[1]!] = m[2]!;
  }
  return out;
}

function appendOrReplaceEnv(updates: Record<string, string>) {
  const current = fs.existsSync(ENV_PATH) ? fs.readFileSync(ENV_PATH, 'utf8') : '';
  let next = current;
  for (const [k, v] of Object.entries(updates)) {
    const re = new RegExp(`^${k}=.*$`, 'm');
    const line = `${k}=${v}`;
    if (re.test(next)) {
      next = next.replace(re, line);
    } else {
      if (!next.endsWith('\n')) next += '\n';
      next += line + '\n';
    }
  }
  fs.writeFileSync(ENV_PATH, next);
}

function rules(): PolicyRule[] {
  const chainId = String(ARC_CHAIN_ID);
  const maxValue = '0x' + MAX_TX_VALUE_WEI.toString(16);

  return [
    {
      name: 'Arc send <= 0.5 ARC',
      method: 'eth_sendTransaction',
      action: 'ALLOW',
      conditions: [
        { field_source: 'ethereum_transaction', field: 'chain_id', operator: 'eq', value: chainId },
        { field_source: 'ethereum_transaction', field: 'value',    operator: 'lte', value: maxValue },
      ],
    },
    {
      name: 'Arc sign tx <= 0.5 ARC',
      method: 'eth_signTransaction',
      action: 'ALLOW',
      conditions: [
        { field_source: 'ethereum_transaction', field: 'chain_id', operator: 'eq', value: chainId },
        { field_source: 'ethereum_transaction', field: 'value',    operator: 'lte', value: maxValue },
      ],
    },
    {
      name: 'Allow personal_sign',
      method: 'personal_sign',
      action: 'ALLOW',
      conditions: [],
    },
  ];
}

async function main() {
  const force = process.argv.includes('--force');
  const env = readEnv();

  if (!force && (env.PRIVY_AUTH_PRIVATE_KEY || env.PRIVY_OWNER_KEY_QUORUM_ID || env.PRIVY_POLICY_ID)) {
    console.error('Privy bootstrap already present in .env. Re-run with --force to recreate.');
    process.exit(1);
  }

  console.log('Step 1/3: generating P-256 authorization keypair…');
  const { privateKey, publicKey } = generateP256Keypair();
  console.log(`  public key (base64, SPKI DER): ${publicKey.slice(0, 32)}…`);

  console.log('Step 2/3: creating key quorum on Privy…');
  const quorum = await createKeyQuorum({
    publicKey,
    displayName: 'Honeybee agent fleet owner',
  });
  console.log(`  key_quorum_id = ${quorum.id}`);

  console.log('Step 3/3: creating chain-locked policy…');
  const policy = await createPolicy({
    name: 'Honeybee Arc-only (≤ 0.5 ARC per tx)',
    chain_type: 'ethereum',
    rules: rules(),
  });
  console.log(`  policy_id = ${policy.id}`);

  appendOrReplaceEnv({
    PRIVY_AUTH_PRIVATE_KEY: privateKey,
    PRIVY_AUTH_PUBLIC_KEY: publicKey,
    PRIVY_OWNER_KEY_QUORUM_ID: quorum.id,
    PRIVY_POLICY_ID: policy.id,
  });

  console.log('');
  console.log('Wrote PRIVY_AUTH_PRIVATE_KEY / PRIVY_AUTH_PUBLIC_KEY /');
  console.log('      PRIVY_OWNER_KEY_QUORUM_ID / PRIVY_POLICY_ID to .env');
  console.log('Next: `make provision-agents` to mint the agent wallets.');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
