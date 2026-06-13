/**
 * Privy embedded wallet — server-managed key, never leaves Privy's TEE.
 *
 * Real integration (uncomment and `npm i @privy-io/server-auth` when keys arrive):
 *
 *   import { PrivyClient } from '@privy-io/server-auth';
 *   const privy = new PrivyClient(process.env.PRIVY_APP_ID!, process.env.PRIVY_APP_SECRET!);
 *
 *   export async function createAgentWallet() {
 *     const w = await privy.walletApi.create({ chainType: 'ethereum' });
 *     return { id: w.id, address: w.address };
 *   }
 *
 *   export async function signMessage(walletId: string, message: string) {
 *     const { signature } = await privy.walletApi.ethereum.signMessage({ walletId, message });
 *     return signature;
 *   }
 *
 *   export async function sendTx(walletId: string, tx: any) {
 *     return privy.walletApi.ethereum.sendTransaction({
 *       walletId, chainId: Number(process.env.ARC_CHAIN_ID), transaction: tx,
 *     });
 *   }
 *
 * For the MVP / DRY_RUN we expose a deterministic stub address so the UI works
 * end-to-end and you can ship the real signer behind the same interface later.
 */
import { createHash } from 'node:crypto';

export interface AgentWallet {
  id: string;
  address: string;
  chain: 'arc';
}

const _mockWallets = new Map<string, AgentWallet>();

export async function createAgentWallet(label?: string): Promise<AgentWallet> {
  if (process.env.PRIVY_APP_ID && process.env.PRIVY_APP_SECRET) {
    // TODO: wire @privy-io/server-auth here.
    // Until then, fall through to the deterministic mock so the UI works.
  }
  const seed = (label ?? Date.now().toString()) + (process.env.PRIVY_APP_ID ?? 'demo');
  const h = createHash('sha256').update(seed).digest('hex');
  const wallet: AgentWallet = {
    id: 'pw_' + h.slice(0, 24),
    address: '0x' + h.slice(0, 40),
    chain: 'arc',
  };
  _mockWallets.set(wallet.id, wallet);
  return wallet;
}

export async function getAgentWallet(id: string): Promise<AgentWallet | null> {
  return _mockWallets.get(id) ?? null;
}

export async function getPrivyWalletAddress(): Promise<string | null> {
  const pinned = process.env.PRIVY_WALLET_ID;
  if (pinned) {
    const w = _mockWallets.get(pinned);
    if (w) return w.address;
  }
  // If not pinned and no real Privy keys, return the demo address derived from app id.
  const appId = process.env.PRIVY_APP_ID;
  if (!appId) return null;
  const h = createHash('sha256').update(appId).digest('hex');
  return '0x' + h.slice(0, 40);
}

export async function signTypedDataViaPrivy(_walletId: string, _payload: unknown): Promise<string> {
  throw new Error('Privy signing not wired yet. Add PRIVY_APP_ID + PRIVY_APP_SECRET and install @privy-io/server-auth.');
}
