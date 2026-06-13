/**
 * Arc chain client.
 *
 * Uses viem with a custom chain definition. Replace the placeholder
 * chainId / RPC once you have the real Arc testnet values — only this
 * file needs to change.
 */
import { createPublicClient, createWalletClient, http, defineChain } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

const ARC_CHAIN_ID = Number(process.env.ARC_CHAIN_ID ?? 421614);            // placeholder
const ARC_RPC_URL  = process.env.ARC_RPC_URL  ?? 'https://rpc.arc.network'; // placeholder
const ARC_EXPLORER = process.env.ARC_EXPLORER_URL ?? '';

export const arc = defineChain({
  id: ARC_CHAIN_ID,
  name: 'Arc Testnet',
  nativeCurrency: { name: 'Arc', symbol: 'ARC', decimals: 18 },
  rpcUrls: { default: { http: [ARC_RPC_URL] } },
  blockExplorers: ARC_EXPLORER ? { default: { name: 'Arc Explorer', url: ARC_EXPLORER } } : undefined,
  testnet: true,
});

export function publicArc() {
  return createPublicClient({ chain: arc, transport: http(ARC_RPC_URL) });
}

/**
 * Wallet client backed by a raw deployer key. For production paths, the
 * AGENT'S key is held by Privy (see ../wallet/privy.ts) and we sign via
 * the Privy server SDK. This helper is for the test/deploy/local-anchor flow.
 */
export function walletArcFromEnv() {
  const pk = process.env.DEPLOYER_PRIVATE_KEY;
  if (!pk) return null;
  const account = privateKeyToAccount(pk.startsWith('0x') ? (pk as `0x${string}`) : (`0x${pk}` as `0x${string}`));
  return createWalletClient({ account, chain: arc, transport: http(ARC_RPC_URL) });
}

export function arcExplorerTxUrl(tx: string): string | null {
  return ARC_EXPLORER ? `${ARC_EXPLORER.replace(/\/$/, '')}/tx/${tx}` : null;
}
