/**
 * Minimal x402-style payment gate for HTTP endpoints.
 *
 * NOT a full implementation of the x402 spec (https://x402.org). We borrow
 * the shape — HTTP 402 with payment requirements, retry with proof-of-payment
 * header — but skip the EIP-712 facilitator handshake because (a) Arc isn't
 * in the x402.org facilitator's allowlist and (b) we want the demo to be
 * self-contained.
 *
 * Flow:
 *   1. Client GET /signal             → 402 { paymentRequirements: {...} }
 *   2. Client builds USDC.transfer()  via its Privy wallet
 *   3. Client retries with header     X-PAYMENT: <tx_hash>
 *   4. We verify on-chain (viem):
 *        - tx exists, status=success
 *        - to = USDC contract
 *        - decoded transfer(to=ourAddress, amount >= price)
 *        - tx within MAX_AGE_BLOCKS of head (prevents replay)
 *   5. On success → call the handler; on failure → 402 again with reason
 */
import { decodeFunctionData, getAddress } from 'viem';

import { publicArc, arc } from '../chain/arc.js';
import { USDC, ERC20_ABI, USDC_DECIMALS, baseUnitsToUsdc } from '../chain/usdc.js';
import { emitActivity } from './events.js';

const MAX_AGE_BLOCKS = 500n;

export interface PaymentRequirements {
  scheme: 'x402-arc-usdc-v0';
  network: 'arc-testnet';
  chainId: number;
  asset: typeof USDC;
  assetSymbol: 'USDC';
  decimals: number;
  /** Where the client should send the USDC. */
  recipient: `0x${string}`;
  /** Amount in USDC base units (6 decimals). */
  amount: string;
  /** Same amount, human readable. */
  amountUsdc: number;
  description: string;
  /** Optional opaque tag the client should echo in the X-PAYMENT-CONTEXT header. */
  context?: string;
}

interface VerifyOk { ok: true; txHash: `0x${string}`; payer: `0x${string}`; baseUnits: bigint; }
interface VerifyErr { ok: false; reason: string; }

/** Used spent tx hashes (in-memory). Prevents one payment from unlocking N responses. */
const usedTxHashes = new Set<string>();

async function verifyPayment(args: {
  txHash: `0x${string}`;
  expectedRecipient: `0x${string}`;
  expectedAmount: bigint;
}): Promise<VerifyOk | VerifyErr> {
  if (usedTxHashes.has(args.txHash.toLowerCase())) {
    return { ok: false, reason: 'tx already used' };
  }

  const client = publicArc();
  let tx;
  let receipt;
  try {
    [tx, receipt] = await Promise.all([
      client.getTransaction({ hash: args.txHash }),
      client.getTransactionReceipt({ hash: args.txHash }),
    ]);
  } catch {
    return { ok: false, reason: 'tx not found (may still be pending — wait for receipt)' };
  }
  if (!tx || !receipt) return { ok: false, reason: 'tx not found' };
  if (receipt.status !== 'success') return { ok: false, reason: 'tx reverted' };

  if (getAddress(tx.to ?? '0x0') !== getAddress(USDC)) {
    return { ok: false, reason: `tx.to != USDC (got ${tx.to})` };
  }

  let decoded;
  try {
    decoded = decodeFunctionData({ abi: ERC20_ABI, data: tx.input });
  } catch {
    return { ok: false, reason: 'failed to decode calldata' };
  }
  if (decoded.functionName !== 'transfer') {
    return { ok: false, reason: `not a transfer() call (got ${decoded.functionName})` };
  }
  const [to, amount] = decoded.args as [`0x${string}`, bigint];

  if (getAddress(to) !== getAddress(args.expectedRecipient)) {
    return { ok: false, reason: `recipient mismatch: paid ${to}, expected ${args.expectedRecipient}` };
  }
  if (amount < args.expectedAmount) {
    return { ok: false, reason: `amount too small: paid ${amount}, expected ≥ ${args.expectedAmount}` };
  }

  const head = await client.getBlockNumber();
  if (head - receipt.blockNumber > MAX_AGE_BLOCKS) {
    return { ok: false, reason: `tx too old (>${MAX_AGE_BLOCKS} blocks)` };
  }

  usedTxHashes.add(args.txHash.toLowerCase());
  return { ok: true, txHash: args.txHash, payer: tx.from as `0x${string}`, baseUnits: amount };
}

/**
 * Wrap a Fastify handler so it requires USDC payment before execution.
 * The handler receives the verified payment context.
 */
export function requireUsdcPayment(opts: {
  /** Who gets paid. */
  recipient: `0x${string}`;
  /** Payee's agent label (for logs / activity feed). */
  recipientLabel?: string;
  /** Price in USDC base units (6 decimals). */
  priceBaseUnits: bigint;
  /** Description shown in 402 body. */
  description: string;
  /** What to do after verifying payment. */
  handler: (ctx: { payer: `0x${string}`; txHash: `0x${string}`; baseUnits: bigint }) => Promise<unknown> | unknown;
}) {
  return async (req: { headers: Record<string, string | string[] | undefined> }, reply: {
    code: (n: number) => unknown; send: (b: unknown) => unknown;
  }) => {
    const requirements: PaymentRequirements = {
      scheme: 'x402-arc-usdc-v0',
      network: 'arc-testnet',
      chainId: arc.id,
      asset: USDC,
      assetSymbol: 'USDC',
      decimals: USDC_DECIMALS,
      recipient: opts.recipient,
      amount: opts.priceBaseUnits.toString(),
      amountUsdc: baseUnitsToUsdc(opts.priceBaseUnits),
      description: opts.description,
    };

    const header = req.headers['x-payment'];
    const txHash = (Array.isArray(header) ? header[0] : header) as `0x${string}` | undefined;

    if (!txHash) {
      emitActivity({
        kind: 'x402.required',
        actor: opts.recipientLabel,
        summary: `${opts.recipientLabel ?? opts.recipient.slice(0, 8) + '…'} requires $${requirements.amountUsdc.toFixed(3)} USDC`,
        details: { requirements },
      });
      (reply as any).code(402);
      return { error: 'payment required', paymentRequirements: requirements };
    }

    const verify = await verifyPayment({
      txHash,
      expectedRecipient: opts.recipient,
      expectedAmount: opts.priceBaseUnits,
    });
    if (!verify.ok) {
      (reply as any).code(402);
      return { error: `payment verification failed: ${verify.reason}`, paymentRequirements: requirements };
    }

    emitActivity({
      kind: 'x402.verified',
      actor: opts.recipientLabel,
      counterparty: verify.payer,
      summary: `${opts.recipientLabel ?? 'service'} received $${baseUnitsToUsdc(verify.baseUnits).toFixed(3)} USDC from ${verify.payer.slice(0, 8)}…`,
      details: { txHash: verify.txHash, amount: verify.baseUnits.toString() },
    });

    const result = await opts.handler({
      payer: verify.payer,
      txHash: verify.txHash,
      baseUnits: verify.baseUnits,
    });
    return result;
  };
}
