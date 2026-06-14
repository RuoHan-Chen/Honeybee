/**
 * AttestationRegistry + AgentIdentity client.
 *
 * Two modes:
 *   1. ANCHOR_MODE=onchain — writes real txs to the contracts on Arc.
 *      Requires:
 *        - AGENT_IDENTITY_ADDRESS
 *        - ATTESTATION_REGISTRY_ADDRESS
 *        - DEPLOYER_PRIVATE_KEY  (or Privy wallet integration; see ../wallet/privy.ts)
 *        - ENS_AGENT_LABEL       (so we know which identity node to attest as)
 *   2. ANCHOR_MODE=mock (default) — returns a deterministic fake tx hash so
 *      the full flow (UI, ledger mirror, reputation aggregation) works without
 *      gas, RPC, or contract deployment. Useful for local dev + hackathon demos.
 *
 * Callers (server.ts) still pass `ens` as a string; this module resolves it to
 * the on-chain `bytes32 node` via either AgentIdentity.nodeFor(label) on-chain
 * or a local namehash computation as a fallback.
 */
import { createHash } from 'node:crypto';
import { encodeFunctionData, keccak256, toHex, encodePacked, stringToBytes } from 'viem';

import { publicArc, walletArcFromEnv, arcExplorerTxUrl, arc } from './arc.js';
import { sendTxFromPrivy } from '../wallet/privy.js';

const REGISTRY = (process.env.ATTESTATION_REGISTRY_ADDRESS ?? '') as `0x${string}` | '';
const IDENTITY = (process.env.AGENT_IDENTITY_ADDRESS ?? '') as `0x${string}` | '';
const MODE = (process.env.ANCHOR_MODE ?? 'mock').toLowerCase();

const REGISTRY_ABI = [
  {
    type: 'function', name: 'attestResearch', stateMutability: 'nonpayable',
    inputs: [
      { name: 'researchHash', type: 'bytes32' },
      { name: 'agentNode',    type: 'bytes32' },
      { name: 'marketId',     type: 'string'  },
    ],
    outputs: [],
  },
  {
    type: 'function', name: 'attestTrade', stateMutability: 'nonpayable',
    inputs: [
      { name: 'recId',      type: 'bytes32' },
      { name: 'agentNode',  type: 'bytes32' },
      { name: 'user',       type: 'address' },
      { name: 'marketId',   type: 'string'  },
      { name: 'side',       type: 'uint8'   },
      { name: 'priceE6',    type: 'uint256' },
      { name: 'sizeUsdE6',  type: 'uint256' },
    ],
    outputs: [],
  },
  {
    type: 'function', name: 'attestResolution', stateMutability: 'nonpayable',
    inputs: [
      { name: 'recId',            type: 'bytes32' },
      { name: 'resolvedOutcome',  type: 'string'  },
      { name: 'pnlUsdE6',         type: 'int256'  },
    ],
    outputs: [],
  },
] as const;

const IDENTITY_ABI = [
  { type: 'function', name: 'parentNode', stateMutability: 'view', inputs: [],
    outputs: [{ name: '', type: 'bytes32' }] },
  { type: 'function', name: 'nodeFor', stateMutability: 'view',
    inputs: [{ name: 'label', type: 'string' }],
    outputs: [{ name: '', type: 'bytes32' }] },
  { type: 'function', name: 'addrOf', stateMutability: 'view',
    inputs: [{ name: 'node', type: 'bytes32' }],
    outputs: [{ name: '', type: 'address' }] },
] as const;

export interface AnchorResult {
  tx_hash: string;
  block_number: number | null;
  chain_id: number;
  explorer_url: string | null;
  mock: boolean;
  agent_node?: `0x${string}`;
}

function mockTx(seed: string, node?: `0x${string}`): AnchorResult {
  const h = '0x' + createHash('sha256').update(seed).digest('hex');
  return {
    tx_hash: h, block_number: null, chain_id: 0,
    explorer_url: null, mock: true,
    agent_node: node,
  };
}

function ensureBytes32(input: string): `0x${string}` {
  if (/^0x[0-9a-fA-F]{64}$/.test(input)) return input as `0x${string}`;
  return keccak256(toHex(input));
}

/**
 * ENS-compatible namehash (EIP-137). Mirror of AgentIdentity._namehash.
 * Used to derive `node` locally without an RPC round-trip.
 */
function namehash(name: string): `0x${string}` {
  if (!name) return ('0x' + '00'.repeat(32)) as `0x${string}`;
  let node = ('0x' + '00'.repeat(32)) as `0x${string}`;
  const labels = name.split('.');
  for (let i = labels.length - 1; i >= 0; i--) {
    const labelHash = keccak256(stringToBytes(labels[i]!));
    node = keccak256(encodePacked(['bytes32', 'bytes32'], [node, labelHash]));
  }
  return node;
}

/**
 * Resolve a user-friendly identifier to a bytes32 agent node.
 * Accepts:
 *   - "alpha-trader"                  → label under ENS_PARENT
 *   - "alpha-trader.honeybee.agent"   → full dotted name
 *   - "0x<64 hex>"                    → already a node, passthrough
 */
function resolveAgentNode(idOrLabelOrName: string): `0x${string}` {
  if (/^0x[0-9a-fA-F]{64}$/.test(idOrLabelOrName)) {
    return idOrLabelOrName as `0x${string}`;
  }
  const parent = process.env.ENS_PARENT ?? 'honeybee.agent';
  const full = idOrLabelOrName.includes('.')
    ? idOrLabelOrName
    : `${idOrLabelOrName}.${parent}`;
  return namehash(full);
}

async function send(args: {
  fn: 'attestResearch' | 'attestTrade' | 'attestResolution';
  params: unknown[];
  agentNode?: `0x${string}`;
  /**
   * If provided, the tx is signed and submitted by this Privy wallet (so
   * msg.sender == the agent's identity address, satisfying AttestationRegistry's
   * "not agent addr" require). If omitted, falls back to the env-derived
   * deployer key (only valid for trade/resolution attestations or for the
   * legacy demo identity).
   */
  fromWalletId?: string;
}): Promise<AnchorResult> {
  if (MODE !== 'onchain' || !REGISTRY) {
    return mockTx(JSON.stringify(args), args.agentNode);
  }

  // Privy-signed path: encode the call ourselves and route via the agent wallet.
  if (args.fromWalletId) {
    const data = encodeFunctionData({
      abi: REGISTRY_ABI,
      functionName: args.fn,
      args: args.params as never,
    });
    const { hash } = await sendTxFromPrivy({
      walletId: args.fromWalletId,
      to: REGISTRY,
      data,
    });
    let blockNumber: number | null = null;
    try {
      const receipt = await publicArc().waitForTransactionReceipt({ hash, timeout: 30_000 });
      blockNumber = Number(receipt.blockNumber);
    } catch { /* leave null */ }
    return {
      tx_hash: hash,
      block_number: blockNumber,
      chain_id: arc.id,
      explorer_url: arcExplorerTxUrl(hash),
      mock: false,
      agent_node: args.agentNode,
    };
  }

  // Legacy / deployer-signed path.
  const wallet = walletArcFromEnv();
  if (!wallet) return mockTx(JSON.stringify(args), args.agentNode);
  const hash = await wallet.writeContract({
    address: REGISTRY,
    abi: REGISTRY_ABI,
    functionName: args.fn,
    args: args.params as never,
  });
  let blockNumber: number | null = null;
  try {
    const receipt = await publicArc().waitForTransactionReceipt({ hash, timeout: 30_000 });
    blockNumber = Number(receipt.blockNumber);
  } catch { /* leave null; UI can poll */ }
  return {
    tx_hash: hash,
    block_number: blockNumber,
    chain_id: arc.id,
    explorer_url: arcExplorerTxUrl(hash),
    mock: false,
    agent_node: args.agentNode,
  };
}

export async function anchorResearch(input: {
  researchHash: string;
  /** ENS label, full dotted name, or bytes32 node. */
  ens: string;
  marketId: string;
  /** Privy walletId of the agent — must own the identity node (sig check). */
  fromWalletId?: string;
}): Promise<AnchorResult> {
  const node = resolveAgentNode(input.ens);
  return send({
    fn: 'attestResearch',
    params: [ensureBytes32(input.researchHash), node, input.marketId],
    agentNode: node,
    fromWalletId: input.fromWalletId,
  });
}

export async function anchorTrade(input: {
  recId: string;
  /** ENS label, full dotted name, or bytes32 node. Defaults to ENS_AGENT_LABEL env. */
  ens?: string;
  user: `0x${string}`;
  marketId: string;
  side: 'BUY' | 'SELL';
  price: number;
  sizeUsd: number;
  /** Privy walletId of the agent — must own the identity node. */
  fromWalletId?: string;
}): Promise<AnchorResult> {
  const ensRef = input.ens ?? process.env.ENS_AGENT_LABEL ?? '';
  const node = resolveAgentNode(ensRef);
  return send({
    fn: 'attestTrade',
    params: [
      ensureBytes32(input.recId),
      node,
      input.user,
      input.marketId,
      input.side === 'BUY' ? 0 : 1,
      BigInt(Math.round(input.price * 1_000_000)),
      BigInt(Math.round(input.sizeUsd * 1_000_000)),
    ],
    agentNode: node,
    fromWalletId: input.fromWalletId,
  });
}

export async function anchorResolution(input: {
  recId: string;
  resolvedOutcome: string;
  pnlUsd: number;
  /**
   * Privy walletId of the agent that anchored the original Trade. The
   * AttestationRegistry reads the agentNode from the stored Trade and
   * requires msg.sender == addrOf(agentNode), so the resolution MUST come
   * from the same agent's wallet.
   */
  fromWalletId?: string;
}): Promise<AnchorResult> {
  return send({
    fn: 'attestResolution',
    params: [
      ensureBytes32(input.recId),
      input.resolvedOutcome,
      BigInt(Math.round(input.pnlUsd * 1_000_000)),
    ],
    fromWalletId: input.fromWalletId,
  });
}

/**
 * Read-only identity lookup. Returns null if identity contract not configured
 * (e.g. in mock mode).
 */
export async function lookupAgent(label: string): Promise<
  { node: `0x${string}`; addr: `0x${string}` | null } | null
> {
  if (!IDENTITY) {
    return { node: resolveAgentNode(label), addr: null };
  }
  const client = publicArc();
  const node = await client.readContract({
    address: IDENTITY, abi: IDENTITY_ABI, functionName: 'nodeFor', args: [label],
  });
  const addr = await client.readContract({
    address: IDENTITY, abi: IDENTITY_ABI, functionName: 'addrOf', args: [node],
  });
  return { node, addr: addr === '0x0000000000000000000000000000000000000000' ? null : addr };
}

export { namehash, resolveAgentNode };
