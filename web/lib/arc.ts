/**
 * Tiny Arc RPC client. No viem dependency in the web package — we only need
 * eth_getBalance + eth_call(balanceOf), both trivial over fetch.
 */
const RPC = process.env.NEXT_PUBLIC_ARC_RPC_URL || 'https://rpc.testnet.arc.network';
const USDC = '0x3600000000000000000000000000000000000000';

let _id = 0;
async function rpc<T = unknown>(method: string, params: unknown[]): Promise<T> {
  const r = await fetch(RPC, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: ++_id, method, params }),
  });
  const j = await r.json();
  if (j.error) throw new Error(`${method}: ${j.error.message}`);
  return j.result as T;
}

/** Native ARC balance in 18-decimal units (whole + fractional). */
export async function arcBalance(address: string): Promise<number> {
  const hex = await rpc<string>('eth_getBalance', [address, 'latest']);
  return Number(BigInt(hex)) / 1e18;
}

/** USDC ERC-20 balance in 6-decimal units. */
export async function usdcBalance(address: string): Promise<number> {
  // balanceOf(address) selector = 0x70a08231
  const padded = address.toLowerCase().replace(/^0x/, '').padStart(64, '0');
  const data = '0x70a08231' + padded;
  const hex = await rpc<string>('eth_call', [{ to: USDC, data }, 'latest']);
  return Number(BigInt(hex)) / 1e6;
}

export async function balancesFor(address: string): Promise<{ arcBalance: number; usdcBalance: number }> {
  const [arc, usdc] = await Promise.all([
    arcBalance(address).catch(() => 0),
    usdcBalance(address).catch(() => 0),
  ]);
  // Keys must match the fleet card's a.arcBalance / a.usdcBalance.
  return { arcBalance: arc, usdcBalance: usdc };
}
