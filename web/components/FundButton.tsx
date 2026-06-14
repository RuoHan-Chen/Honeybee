'use client';

/**
 * One-tap Blink deposit, the way Blink advertises it — no form, no address to
 * type. Sits next to "Connect wallet" in the nav. Funds the connected wallet
 * with USDC; the hosted Blink flow handles source-wallet connect + routing.
 */
import { useBlinkDeposit } from '@swype-org/deposit/react';
import { useUser } from './UserWallet';

const SANDBOX = (process.env.NEXT_PUBLIC_BLINK_ENV ?? 'sandbox') !== 'production';
// Destination: Base (USDC). Sandbox → Base Sepolia testnet USDC.
const CHAIN = SANDBOX ? 84532 : 8453;
const TOKEN = SANDBOX
  ? '0x036CbD53842c5426634e7929541eC2318f3dCF7e' // Base Sepolia USDC
  : '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'; // Base USDC
const DEFAULT_AMOUNT = 25;

export function FundButton() {
  const u = useUser();
  const { status, error, displayMessage, requestDeposit } = useBlinkDeposit({
    signer: '/api/sign-payment',
    merchantId: process.env.NEXT_PUBLIC_BLINK_MERCHANT_ID,
    environment: SANDBOX ? 'sandbox' : 'production',
  });

  if (!u.address) return null; // shown only once connected (next to the address)

  const busy = status === 'signer-loading' || status === 'iframe-active';

  return (
    <button
      type="button"
      disabled={busy}
      onClick={() =>
        requestDeposit({
          amount: DEFAULT_AMOUNT,
          chainId: CHAIN,
          token: TOKEN,
          address: u.address as `0x${string}`,
        })
      }
      title={error ? displayMessage : 'Deposit USDC in one tap (Blink)'}
      className="shrink-0 rounded-lg bg-gold px-3 py-1.5 text-xs font-semibold text-midnight transition hover:opacity-90 disabled:opacity-50"
    >
      {busy ? 'Funding…' : 'Fund'}
    </button>
  );
}
