/**
 * ENS resolution via viem.
 *
 *   - resolveEns(name)         — mainnet lookup, used for the human-facing ENS_NAME.
 *   - resolveEnsOnSepolia(name) — Sepolia lookup, used to verify agent subnames
 *                                  (e.g. alpha-trader.honeybee-agents.eth).
 */
import { createPublicClient, http } from 'viem';
import { mainnet, sepolia } from 'viem/chains';

const mainnetClient = createPublicClient({
  chain: mainnet,
  transport: http(),
});

const sepoliaClient = createPublicClient({
  chain: sepolia,
  transport: http(process.env.SEPOLIA_RPC_URL ?? 'https://ethereum-sepolia-rpc.publicnode.com'),
});

export async function resolveEns(name: string): Promise<string | null> {
  try {
    return await mainnetClient.getEnsAddress({ name });
  } catch {
    return null;
  }
}

/**
 * Resolve a Sepolia-side ENS name to an address (read-only).
 *
 * Uses viem's UniversalResolver path by default. We pin the ENS Sepolia
 * UniversalResolver explicitly because the public viem default sometimes
 * lags behind mid-migration deployments.
 */
const SEPOLIA_UNIVERSAL_RESOLVER =
  (process.env.ENS_SEPOLIA_UNIVERSAL_RESOLVER as `0x${string}` | undefined) ??
  '0xeEeEEEeE14D718C2B47D9923Deab1335E144EeEe';

export async function resolveEnsOnSepolia(name: string): Promise<`0x${string}` | null> {
  try {
    const addr = await sepoliaClient.getEnsAddress({
      name,
      universalResolverAddress: SEPOLIA_UNIVERSAL_RESOLVER,
    });
    return addr ?? null;
  } catch {
    return null;
  }
}
