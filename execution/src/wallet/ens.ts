/**
 * ENS resolution via viem (read-only path).
 */
import { createPublicClient, http } from 'viem';
import { mainnet } from 'viem/chains';

const client = createPublicClient({
  chain: mainnet,
  transport: http(),
});

export async function resolveEns(name: string): Promise<string | null> {
  try {
    return await client.getEnsAddress({ name });
  } catch {
    return null;
  }
}
