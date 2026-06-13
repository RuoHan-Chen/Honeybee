/**
 * AttestationRegistry client.
 *
 * Two modes:
 *   1. ANCHOR_MODE=onchain — writes real txs to the contract on Arc.
 *      Requires ATTESTATION_REGISTRY_ADDRESS + (DEPLOYER_PRIVATE_KEY or PRIVY_WALLET_ID).
 *   2. ANCHOR_MODE=mock (default) — returns a deterministic fake tx hash so
 *      the full flow (UI, ledger mirror, reputation aggregation) works without
 *      gas, RPC, or contract deployment. Useful for local dev + hackathon demos.
 */
import { createHash } from 'node:crypto';
import { keccak256, toHex } from 'viem';

import { publicArc, walletArcFromEnv, arcExplorerTxUrl, arc } from './arc.js';

const REGISTRY = (process.env.ATTESTATION_REGISTRY_ADDRESS ?? '') as `0x${string}` | '';
const MODE = (process.env.ANCHOR_MODE ?? 'mock').toLowerCase();

const REGISTRY_ABI = [
  {
    type: 'function', name: 'attestResearch', stateMutability: 'nonpayable',
    inputs: [
      { name: 'researchHash', type: 'bytes32' },
      { name: 'ens',          type: 'string'  },
      { name: 'marketId',     type: 'string'  },
    ],
    outputs: [],
  },
  {
    type: 'function', name: 'attestTrade', stateMutability: 'nonpayable',
    inputs: [
      { name: 'recId',      type: 'bytes32' },
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

export interface AnchorResult {
  tx_hash: string;
  block_number: number | null;
  chain_id: number;
  explorer_url: string | null;
  mock: boolean;
}

function mockTx(seed: string): AnchorResult {
  const h = '0x' + createHash('sha256').update(seed).digest('hex');
  return { tx_hash: h, block_number: null, chain_id: 0, explorer_url: null, mock: true };
}

function ensureBytes32(input: string): `0x${string}` {
  // accept already-hex bytes32 ("0x" + 64 hex) or arbitrary string → keccak256
  if (/^0x[0-9a-fA-F]{64}$/.test(input)) return input as `0x${string}`;
  return keccak256(toHex(input));
}

async function send(args: { fn: 'attestResearch' | 'attestTrade' | 'attestResolution'; params: unknown[] }): Promise<AnchorResult> {
  const wallet = walletArcFromEnv();
  if (MODE !== 'onchain' || !REGISTRY || !wallet) {
    return mockTx(JSON.stringify(args));
  }
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
  };
}

export async function anchorResearch(input: {
  researchHash: string; ens: string; marketId: string;
}): Promise<AnchorResult> {
  return send({
    fn: 'attestResearch',
    params: [ensureBytes32(input.researchHash), input.ens, input.marketId],
  });
}

export async function anchorTrade(input: {
  recId: string; user: `0x${string}`; marketId: string;
  side: 'BUY' | 'SELL'; price: number; sizeUsd: number;
}): Promise<AnchorResult> {
  return send({
    fn: 'attestTrade',
    params: [
      ensureBytes32(input.recId),
      input.user,
      input.marketId,
      input.side === 'BUY' ? 0 : 1,
      BigInt(Math.round(input.price * 1_000_000)),
      BigInt(Math.round(input.sizeUsd * 1_000_000)),
    ],
  });
}

export async function anchorResolution(input: {
  recId: string; resolvedOutcome: string; pnlUsd: number;
}): Promise<AnchorResult> {
  return send({
    fn: 'attestResolution',
    params: [
      ensureBytes32(input.recId),
      input.resolvedOutcome,
      BigInt(Math.round(input.pnlUsd * 1_000_000)),
    ],
  });
}
