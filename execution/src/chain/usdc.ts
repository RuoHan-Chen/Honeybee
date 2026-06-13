/**
 * USDC on Arc.
 *
 * Arc is "stablecoin-native": the native gas token IS USDC, and an ERC-20
 * interface is exposed at a well-known address so existing EVM tooling
 * (transferFrom, allowances, etc.) works.
 *
 *   native USDC   → 18 decimals (gas token)
 *   ERC-20 USDC   → 6 decimals  (at 0x3600…0000)
 *
 * Both views share the same underlying balance. We use the ERC-20 surface
 * for nanopayments because (a) it's standard ERC-20 calldata and (b)
 * `transfer(address,uint256)` is policy-encodable in Privy.
 */
import { encodeFunctionData } from 'viem';

export const USDC = '0x3600000000000000000000000000000000000000' as const;
export const USDC_DECIMALS = 6;

export const ERC20_ABI = [
  {
    type: 'function', name: 'transfer', stateMutability: 'nonpayable',
    inputs: [
      { name: 'to', type: 'address' },
      { name: 'amount', type: 'uint256' },
    ],
    outputs: [{ name: '', type: 'bool' }],
  },
  {
    type: 'function', name: 'balanceOf', stateMutability: 'view',
    inputs: [{ name: 'owner', type: 'address' }],
    outputs: [{ name: '', type: 'uint256' }],
  },
  {
    type: 'event', name: 'Transfer', anonymous: false,
    inputs: [
      { name: 'from', type: 'address', indexed: true },
      { name: 'to',   type: 'address', indexed: true },
      { name: 'value',type: 'uint256', indexed: false },
    ],
  },
] as const;

/** Convert a human USDC amount (e.g. 0.005) to ERC-20 base units (6 decimals). */
export function usdcToBaseUnits(usd: number): bigint {
  // Round to nearest microunit to avoid 0.1 + 0.2 == 0.30000000000000004 weirdness.
  return BigInt(Math.round(usd * 10 ** USDC_DECIMALS));
}

/** Inverse of usdcToBaseUnits. */
export function baseUnitsToUsdc(base: bigint): number {
  return Number(base) / 10 ** USDC_DECIMALS;
}

/** Build the ERC-20 transfer() calldata for a USDC payment. */
export function encodeUsdcTransfer(to: `0x${string}`, baseUnits: bigint): `0x${string}` {
  return encodeFunctionData({ abi: ERC20_ABI, functionName: 'transfer', args: [to, baseUnits] });
}
