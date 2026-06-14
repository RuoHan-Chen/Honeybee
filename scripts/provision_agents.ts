/**
 * Provision Honeybee's agent fleet.
 *
 * For each agent in AGENTS[], we:
 *   1. Create a Privy wallet on Arc, owned by PRIVY_OWNER_KEY_QUORUM_ID and
 *      constrained by PRIVY_POLICY_ID.
 *   2. Fund the wallet from DEPLOYER_PRIVATE_KEY with FUND_PER_AGENT_WEI.
 *   3. Register an ENS-shaped identity on AgentIdentity, owned by the
 *      deployer. We then setAddr(agent.wallet) and setText('role'|'model'|
 *      'description') so on-chain resolution maps label -> Privy address.
 *   4. Persist the full roster to var/agents.json.
 *
 * The deployer key registers + writes records. Why not the Privy wallet?
 * Because AgentIdentity.register() / setAddr() / setText() only require the
 * record's *owner* to call them; we keep ownership with the deployer so
 * humans can rotate keys. The wallet is the `addr`, which is what
 * AttestationRegistry enforces for attestations.
 */
import 'dotenv/config';
import fs from 'node:fs';
import path from 'node:path';

import {
  createAgentWallet,
  getAgentWallet,
} from '../execution/src/wallet/privy.js';
import { publicArc, walletArcFromEnv, arc, arcExplorerTxUrl } from '../execution/src/chain/arc.js';

const IDENTITY = process.env.AGENT_IDENTITY_ADDRESS as `0x${string}` | undefined;
const FUND_PER_AGENT_WEI = 100_000_000_000_000_000n; // 0.1 ARC

interface AgentSpec {
  label: string;
  role: string;
  model: string;
  description: string;
}

const AGENTS: AgentSpec[] = [
  {
    label: 'alpha-trader',
    role: 'trader',
    model: 'claude-sonnet-4-5',
    description: 'Long-tail prediction market trader with research-driven thesis selection',
  },
  {
    label: 'sports-analyst',
    role: 'research',
    model: 'claude-sonnet-4-5',
    description: 'Sports-market specialist: form analysis, weather, injury reports',
  },
  {
    label: 'politics-analyst',
    role: 'research',
    model: 'claude-sonnet-4-5',
    description: 'Politics + macro markets: polling synthesis and event-driven repricing',
  },
];

const IDENTITY_ABI = [
  {
    type: 'function', name: 'register', stateMutability: 'nonpayable',
    inputs: [
      { name: 'label', type: 'string' },
      { name: 'owner', type: 'address' },
    ],
    outputs: [{ name: 'node', type: 'bytes32' }],
  },
  {
    type: 'function', name: 'setAddr', stateMutability: 'nonpayable',
    inputs: [
      { name: 'node', type: 'bytes32' },
      { name: 'addr', type: 'address' },
    ],
    outputs: [],
  },
  {
    type: 'function', name: 'setText', stateMutability: 'nonpayable',
    inputs: [
      { name: 'node', type: 'bytes32' },
      { name: 'key',  type: 'string'  },
      { name: 'value',type: 'string'  },
    ],
    outputs: [],
  },
  {
    type: 'function', name: 'nodeFor', stateMutability: 'view',
    inputs: [{ name: 'label', type: 'string' }],
    outputs: [{ name: '', type: 'bytes32' }],
  },
  {
    type: 'function', name: 'exists', stateMutability: 'view',
    inputs: [{ name: 'node', type: 'bytes32' }],
    outputs: [{ name: '', type: 'bool' }],
  },
] as const;

interface AgentRecord {
  label: string;
  role: string;
  model: string;
  description: string;
  privyWalletId: string;
  address: `0x${string}`;
  node: `0x${string}`;
  ownerKeyQuorumId: string | null;
  policyIds: string[];
  registerTx: string | null;
  setAddrTx: string | null;
  textTxs: Record<string, string>;
  fundTx: string | null;
  explorer: {
    address: string | null;
    register: string | null;
    setAddr: string | null;
    fund: string | null;
  };
}

async function ensureDeployer() {
  const wallet = walletArcFromEnv();
  if (!wallet) throw new Error('DEPLOYER_PRIVATE_KEY missing (needed to register + fund)');
  if (!IDENTITY) throw new Error('AGENT_IDENTITY_ADDRESS missing');
  return wallet;
}

async function waitReceipt(hash: `0x${string}`) {
  try {
    return await publicArc().waitForTransactionReceipt({ hash, timeout: 60_000 });
  } catch {
    return null;
  }
}

function explorerAddress(addr: string): string | null {
  const base = process.env.ARC_EXPLORER_URL?.replace(/\/$/, '');
  return base ? `${base}/address/${addr}` : null;
}

async function provisionOne(spec: AgentSpec, deployer: ReturnType<typeof walletArcFromEnv>): Promise<AgentRecord> {
  if (!deployer) throw new Error('deployer missing');
  console.log(`\n[${spec.label}] minting Privy wallet…`);
  const wallet = await createAgentWallet();
  console.log(`  wallet ${wallet.id} -> ${wallet.address}  (owner=${wallet.ownerKeyQuorumId ?? 'none'} policies=${wallet.policyIds.join(',') || 'none'})`);

  // Fund
  console.log(`  funding ${FUND_PER_AGENT_WEI} wei from deployer…`);
  const fundTx = await deployer.sendTransaction({
    to: wallet.address,
    value: FUND_PER_AGENT_WEI,
    chain: arc,
  });
  await waitReceipt(fundTx);
  console.log(`  fund tx ${fundTx}`);

  // Register on AgentIdentity (owner = deployer)
  console.log(`  registering identity ${spec.label}.${process.env.ENS_PARENT ?? 'honeybee.agent'}…`);
  let registerTx: `0x${string}` | null = null;
  let node = await publicArc().readContract({
    address: IDENTITY!, abi: IDENTITY_ABI, functionName: 'nodeFor', args: [spec.label],
  }) as `0x${string}`;
  const exists = await publicArc().readContract({
    address: IDENTITY!, abi: IDENTITY_ABI, functionName: 'exists', args: [node],
  }) as boolean;

  if (!exists) {
    registerTx = await deployer.writeContract({
      address: IDENTITY!,
      abi: IDENTITY_ABI,
      functionName: 'register',
      args: [spec.label, deployer.account!.address],
    });
    await waitReceipt(registerTx);
    console.log(`  register tx ${registerTx}`);
  } else {
    console.log(`  already registered (node=${node}); skipping register`);
  }

  // setAddr -> Privy wallet
  console.log(`  setAddr(node, ${wallet.address})…`);
  const setAddrTx = await deployer.writeContract({
    address: IDENTITY!,
    abi: IDENTITY_ABI,
    functionName: 'setAddr',
    args: [node, wallet.address],
  });
  await waitReceipt(setAddrTx);
  console.log(`  setAddr tx ${setAddrTx}`);

  // Text records
  const textTxs: Record<string, string> = {};
  for (const [key, value] of Object.entries({
    role: spec.role,
    model: spec.model,
    description: spec.description,
    'privy.wallet_id': wallet.id,
  })) {
    const tx = await deployer.writeContract({
      address: IDENTITY!,
      abi: IDENTITY_ABI,
      functionName: 'setText',
      args: [node, key, value],
    });
    await waitReceipt(tx);
    textTxs[key] = tx;
    console.log(`  setText(${key}) tx ${tx}`);
  }

  return {
    label: spec.label,
    role: spec.role,
    model: spec.model,
    description: spec.description,
    privyWalletId: wallet.id,
    address: wallet.address,
    node,
    ownerKeyQuorumId: wallet.ownerKeyQuorumId,
    policyIds: wallet.policyIds,
    registerTx: registerTx,
    setAddrTx,
    textTxs,
    fundTx,
    explorer: {
      address: explorerAddress(wallet.address),
      register: registerTx ? arcExplorerTxUrl(registerTx) : null,
      setAddr: arcExplorerTxUrl(setAddrTx),
      fund: arcExplorerTxUrl(fundTx),
    },
  };
}

async function main() {
  const deployer = await ensureDeployer();
  console.log(`Deployer: ${deployer.account!.address}`);
  console.log(`Identity contract: ${IDENTITY}`);
  console.log(`Funding per agent: ${FUND_PER_AGENT_WEI} wei`);

  const results: AgentRecord[] = [];
  for (const spec of AGENTS) {
    try {
      results.push(await provisionOne(spec, deployer));
    } catch (err) {
      console.error(`FAILED to provision ${spec.label}:`, err);
      throw err;
    }
  }

  const outPath = path.resolve(process.cwd(), 'var/agents.json');
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify({
    generatedAt: new Date().toISOString(),
    chainId: arc.id,
    identity: IDENTITY,
    deployer: deployer.account!.address,
    agents: results,
  }, null, 2));

  console.log(`\n✓ Wrote ${results.length} agents to ${outPath}`);
  for (const a of results) {
    console.log(`  ${a.label.padEnd(20)} ${a.address}  (privy ${a.privyWalletId})`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
