'use client';

/**
 * Blink one-tap USDC deposit. Pulls stablecoins from the user's wallet straight
 * into a destination address (here: an agent's wallet) without leaving the app.
 *
 * The destination `address` is passed in (e.g. an agent's on-chain address from
 * the fleet roster) — never hard-coded. Signing happens server-side at
 * /api/sign-payment; the merchant private key never reaches the browser.
 */
import { BlinkDepositButton, useBlinkDeposit } from '@swype-org/deposit/react';

// Default destination chain: Base (Blink-supported). USDC on Base.
const BASE_CHAIN_ID = 8453;
const BASE_USDC = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913';

export interface BlinkDepositProps {
  address: `0x${string}`;     // where the USDC lands (e.g. agent wallet)
  amount: number;             // USD
  chainId?: number;
  token?: string;
  onDeposited?: (transferId: string) => void;
}

export function BlinkDeposit({
  address,
  amount,
  chainId = BASE_CHAIN_ID,
  token = BASE_USDC,
  onDeposited,
}: BlinkDepositProps) {
  const { status, error, displayMessage, requestDeposit } = useBlinkDeposit({
    signer: '/api/sign-payment',
    merchantId: process.env.NEXT_PUBLIC_BLINK_MERCHANT_ID,
  });

  async function handle() {
    // requestDeposit must run inside the user-gesture handler (browsers block
    // iframe creation otherwise).
    const result = await requestDeposit({ amount, chainId, address, token });
    if (result?.transfer?.id) onDeposited?.(result.transfer.id);
  }

  return (
    <div className="flex flex-col gap-2">
      <BlinkDepositButton onClick={handle} loading={status === 'signer-loading'} />
      {error && <p className="text-rose-400 text-sm">{displayMessage}</p>}
      {status === 'completed' && <p className="text-emerald-300 text-sm">Deposit submitted ✓</p>}
    </div>
  );
}
