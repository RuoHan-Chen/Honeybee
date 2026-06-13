/**
 * x402 client: fetch a paid resource, auto-paying via a Privy wallet on Arc.
 *
 * Workflow:
 *   1. GET the URL.
 *   2. If 200 → return body.
 *   3. If 402 → read paymentRequirements, send USDC tx from our Privy wallet,
 *      wait for receipt, retry with X-PAYMENT: <txHash>.
 *   4. If second attempt is still 402 → throw with reason.
 */
import { sendUsdcFromPrivy } from '../wallet/privy.js';
import { publicArc } from '../chain/arc.js';
import { baseUnitsToUsdc } from '../chain/usdc.js';
import { emitActivity } from './events.js';
import type { PaymentRequirements } from './server.js';

export interface X402Receipt {
  paid: boolean;
  /** Cost paid in USDC. 0 if the endpoint was free or already paid. */
  costUsdc: number;
  txHash?: `0x${string}`;
  body: unknown;
}

export async function fetchWithX402(url: string, opts: {
  /** Privy wallet that funds the payment. */
  walletId: string;
  /** Label for activity-feed attribution. */
  payerLabel?: string;
  /** Hard ceiling — refuse to pay more than this many USD per request. */
  maxUsdc?: number;
  init?: RequestInit;
}): Promise<X402Receipt> {
  const maxUsdc = opts.maxUsdc ?? 0.10;

  // Attempt 1: try free.
  const first = await fetch(url, opts.init);
  if (first.status !== 402) {
    return { paid: false, costUsdc: 0, body: await first.json() };
  }

  const reqBody = await first.json() as { paymentRequirements: PaymentRequirements; error?: string };
  const reqt = reqBody.paymentRequirements;
  if (!reqt) throw new Error(`402 with no paymentRequirements: ${JSON.stringify(reqBody)}`);
  if (reqt.scheme !== 'x402-arc-usdc-v0') {
    throw new Error(`unsupported x402 scheme: ${reqt.scheme}`);
  }
  if (reqt.amountUsdc > maxUsdc) {
    throw new Error(`price ${reqt.amountUsdc} USDC exceeds maxUsdc ${maxUsdc}`);
  }

  // Pay.
  const baseUnits = BigInt(reqt.amount);
  const pay = await sendUsdcFromPrivy({
    walletId: opts.walletId,
    to: reqt.recipient,
    baseUnits,
    chainId: reqt.chainId,
  });

  // Wait for receipt so the server can find the tx when it verifies.
  try {
    await publicArc().waitForTransactionReceipt({ hash: pay.hash, timeout: 30_000 });
  } catch {
    // proceed; the server has its own retry-tolerance
  }

  emitActivity({
    kind: 'x402.paid',
    actor: opts.payerLabel,
    counterparty: reqt.recipient,
    summary: `${opts.payerLabel ?? 'agent'} paid $${baseUnitsToUsdc(baseUnits).toFixed(3)} USDC for ${url.replace(/^https?:\/\/[^/]+/, '')}`,
    details: { txHash: pay.hash, amount: baseUnits.toString(), url },
  });

  // Attempt 2: with payment proof.
  const headers = new Headers(opts.init?.headers ?? {});
  headers.set('x-payment', pay.hash);
  const second = await fetch(url, { ...opts.init, headers });
  if (second.status === 402) {
    const errBody = await second.text();
    throw new Error(`payment rejected after tx ${pay.hash}: ${errBody}`);
  }
  if (!second.ok) {
    throw new Error(`paid call still failed: HTTP ${second.status}`);
  }

  return {
    paid: true,
    costUsdc: baseUnitsToUsdc(baseUnits),
    txHash: pay.hash,
    body: await second.json(),
  };
}
