/**
 * Privy server-managed wallets with authorization-key rails.
 *
 * Two layered controls (per Privy's "agentic wallets" recipe):
 *
 *   1. Owner = key_quorum containing a P-256 authorization key.
 *      Every wallet action requires a signed `privy-authorization-signature`
 *      header derived from the auth key — even with the app secret leaked,
 *      an attacker can't move funds without the auth key.
 *
 *   2. Per-wallet policy. Privy enforces chain lock (Arc-only) and value
 *      caps server-side; the wallet refuses to sign anything that doesn't
 *      match `ALLOW` rules.
 *
 * If PRIVY_AUTH_PRIVATE_KEY / PRIVY_OWNER_KEY_QUORUM_ID / PRIVY_POLICY_ID
 * are missing, we degrade to "unrailed" (app-secret-only) wallets so dev
 * flow still works; provisioning sets them up.
 */
import { createHash } from 'node:crypto';

import { signPrivyRequest } from './privy_sign.js';
import { USDC, encodeUsdcTransfer } from '../chain/usdc.js';

export interface AgentWallet {
  id: string;
  address: `0x${string}`;
  chain: 'arc';
  ownerKeyQuorumId: string | null;
  policyIds: string[];
}

export interface SendTxResult {
  hash: `0x${string}`;
  caip2: string;
}

const PRIVY_BASE = 'https://api.privy.io/v1';

function appId(): string | null {
  return process.env.PRIVY_APP_ID || null;
}

function appAuthHeader(): string | null {
  const id = process.env.PRIVY_APP_ID;
  const secret = process.env.PRIVY_APP_SECRET;
  if (!id || !secret) return null;
  return 'Basic ' + Buffer.from(`${id}:${secret}`).toString('base64');
}

/** Owner key quorum + auth-key for signing. May be null if not yet provisioned. */
function ownerConfig(): { ownerId: string; privateKey: string } | null {
  const ownerId = process.env.PRIVY_OWNER_KEY_QUORUM_ID;
  const privateKey = process.env.PRIVY_AUTH_PRIVATE_KEY;
  if (!ownerId || !privateKey) return null;
  return { ownerId, privateKey };
}

function defaultPolicyIds(): string[] {
  const v = process.env.PRIVY_POLICY_ID;
  return v ? [v] : [];
}

/**
 * Low-level Privy request helper.
 *
 *   - Always sends `privy-app-id` + HTTP Basic auth
 *   - For mutating requests (POST/PATCH/DELETE/PUT), if `ownerConfig()` is set
 *     AND `signWithOwner` is true, also signs and attaches
 *     `privy-authorization-signature`.
 */
async function privyFetch<T>(args: {
  path: string;
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE' | 'PUT';
  body?: unknown;
  signWithOwner?: boolean;
}): Promise<T> {
  const basic = appAuthHeader();
  const id = appId();
  if (!basic || !id) throw new Error('Privy not configured (PRIVY_APP_ID / PRIVY_APP_SECRET missing)');

  const method = args.method ?? (args.body !== undefined ? 'POST' : 'GET');
  const url = `${PRIVY_BASE}${args.path}`;
  const headers: Record<string, string> = {
    authorization: basic,
    'privy-app-id': id,
    'content-type': 'application/json',
  };

  if (args.signWithOwner && method !== 'GET') {
    const owner = ownerConfig();
    if (!owner) throw new Error('Owner-signed request requested but PRIVY_AUTH_PRIVATE_KEY/PRIVY_OWNER_KEY_QUORUM_ID missing');
    const sig = signPrivyRequest({
      privateKey: owner.privateKey,
      appId: id,
      method: method as 'POST' | 'PATCH' | 'DELETE' | 'PUT',
      url,
      body: args.body ?? {},
    });
    headers['privy-authorization-signature'] = sig.signature;
  }

  const body = args.body !== undefined ? JSON.stringify(args.body) : undefined;
  const res = await fetch(url, { method, headers, body });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`Privy ${method} ${args.path} ${res.status}: ${text}`);
  }
  return text ? (JSON.parse(text) as T) : ({} as T);
}

// ─── mock fallback for offline dev ─────────────────────────────────────────
const _mockWallets = new Map<string, AgentWallet>();

function mockWallet(label?: string): AgentWallet {
  const seed = (label ?? Date.now().toString()) + (process.env.PRIVY_APP_ID ?? 'demo');
  const h = createHash('sha256').update(seed).digest('hex');
  return {
    id: 'pw_mock_' + h.slice(0, 22),
    address: ('0x' + h.slice(0, 40)) as `0x${string}`,
    chain: 'arc',
    ownerKeyQuorumId: null,
    policyIds: [],
  };
}

// ─── public surface ────────────────────────────────────────────────────────

/**
 * Create a wallet, optionally bound to an owner key quorum + policies.
 * Defaults pull from env so the caller doesn't have to thread args:
 *   - owner = PRIVY_OWNER_KEY_QUORUM_ID
 *   - policy_ids = [PRIVY_POLICY_ID]
 */
export async function createAgentWallet(opts?: {
  ownerKeyQuorumId?: string;
  policyIds?: string[];
}): Promise<AgentWallet> {
  if (!appAuthHeader()) {
    const w = mockWallet();
    _mockWallets.set(w.id, w);
    return w;
  }

  const ownerId = opts?.ownerKeyQuorumId ?? ownerConfig()?.ownerId;
  const policyIds = opts?.policyIds ?? defaultPolicyIds();

  const body: Record<string, unknown> = { chain_type: 'ethereum' };
  if (ownerId) body.owner_id = ownerId;
  if (policyIds.length > 0) body.policy_ids = policyIds;

  // Wallet creation itself doesn't need an authorization signature (no
  // existing owner to authorize the request). Once owned, future mutations
  // and signing actions will.
  const out = await privyFetch<{
    id: string; address: string; owner_id: string | null; policy_ids: string[];
  }>({ path: '/wallets', method: 'POST', body });

  return {
    id: out.id,
    address: out.address as `0x${string}`,
    chain: 'arc',
    ownerKeyQuorumId: out.owner_id,
    policyIds: out.policy_ids ?? [],
  };
}

export async function getAgentWallet(id: string): Promise<AgentWallet | null> {
  if (!appAuthHeader()) return _mockWallets.get(id) ?? null;
  try {
    const out = await privyFetch<{
      id: string; address: string; owner_id: string | null; policy_ids: string[];
    }>({ path: `/wallets/${id}` });
    return {
      id: out.id,
      address: out.address as `0x${string}`,
      chain: 'arc',
      ownerKeyQuorumId: out.owner_id,
      policyIds: out.policy_ids ?? [],
    };
  } catch {
    return null;
  }
}

export async function getPrivyWalletAddress(): Promise<string | null> {
  const pinned = process.env.PRIVY_WALLET_ID;
  if (pinned) {
    const w = await getAgentWallet(pinned);
    return w?.address ?? null;
  }
  return null;
}

/**
 * Sign + broadcast an EVM transaction from a Privy wallet on Arc.
 * If the wallet has an owner, this request will be auto-signed.
 */
export async function sendTxFromPrivy(args: {
  walletId: string;
  to: `0x${string}`;
  valueWei?: bigint;
  data?: `0x${string}`;
  chainId?: number;
}): Promise<SendTxResult> {
  const chainId = args.chainId ?? Number(process.env.ARC_CHAIN_ID ?? 5042002);
  const valueHex = '0x' + (args.valueWei ?? 0n).toString(16);

  const body = {
    method: 'eth_sendTransaction',
    caip2: `eip155:${chainId}`,
    params: {
      transaction: {
        to: args.to,
        value: valueHex,
        chain_id: chainId,
        ...(args.data ? { data: args.data } : {}),
      },
    },
  };

  const out = await privyFetch<{
    method: string;
    data: { hash: string; caip2: string };
  }>({
    path: `/wallets/${args.walletId}/rpc`,
    method: 'POST',
    body,
    signWithOwner: true,
  });

  return { hash: out.data.hash as `0x${string}`, caip2: out.data.caip2 };
}

/**
 * Pay USDC from a Privy wallet. Builds the ERC-20 `transfer(to, baseUnits)`
 * calldata and submits it via the wallet's RPC. Subject to the same auth-key
 * signing + Privy policy enforcement as any other tx.
 */
export async function sendUsdcFromPrivy(args: {
  walletId: string;
  to: `0x${string}`;
  baseUnits: bigint;
  chainId?: number;
}): Promise<SendTxResult> {
  const chainId = args.chainId ?? Number(process.env.ARC_CHAIN_ID ?? 5042002);
  const data = encodeUsdcTransfer(args.to, args.baseUnits);

  const body = {
    method: 'eth_sendTransaction',
    caip2: `eip155:${chainId}`,
    params: {
      transaction: {
        to: USDC,
        value: '0x0',
        chain_id: chainId,
        data,
      },
    },
  };

  const out = await privyFetch<{
    method: string;
    data: { hash: string; caip2: string };
  }>({
    path: `/wallets/${args.walletId}/rpc`,
    method: 'POST',
    body,
    signWithOwner: true,
  });

  return { hash: out.data.hash as `0x${string}`, caip2: out.data.caip2 };
}

export async function signMessageFromPrivy(args: {
  walletId: string;
  message: string;
}): Promise<{ signature: `0x${string}` }> {
  const body = {
    method: 'personal_sign',
    params: { message: args.message, encoding: 'utf-8' },
  };
  const out = await privyFetch<{ data: { signature: string } }>({
    path: `/wallets/${args.walletId}/rpc`,
    method: 'POST',
    body,
    signWithOwner: true,
  });
  return { signature: out.data.signature as `0x${string}` };
}

export async function signTypedDataViaPrivy(walletId: string, _payload: unknown): Promise<string> {
  throw new Error(`signTypedData not yet wired (walletId=${walletId})`);
}

// ─── provisioning helpers (used by scripts) ────────────────────────────────

/** Register a key quorum that owns wallets/policies. Returns its id. */
export async function createKeyQuorum(args: {
  publicKey: string;
  displayName?: string;
  threshold?: number;
}): Promise<{ id: string }> {
  const out = await privyFetch<{ id: string }>({
    path: '/key_quorums',
    method: 'POST',
    body: {
      public_keys: [args.publicKey],
      authorization_threshold: args.threshold ?? 1,
      display_name: args.displayName ?? 'Honeybee owner',
    },
  });
  return { id: out.id };
}

export interface PolicyCondition {
  field_source: string;
  field: string;
  operator: 'eq' | 'neq' | 'lt' | 'lte' | 'gt' | 'gte' | 'in' | 'in_condition_set';
  value: string | number | string[];
  abi?: unknown;
}

export interface PolicyRule {
  name: string;
  method: string;
  conditions: PolicyCondition[];
  action: 'ALLOW' | 'DENY';
}

/** Create a policy. */
export async function createPolicy(policy: {
  name: string;
  chain_type: 'ethereum';
  rules: PolicyRule[];
}): Promise<{ id: string }> {
  const out = await privyFetch<{ id: string }>({
    path: '/policies',
    method: 'POST',
    body: { version: '1.0', ...policy },
  });
  return { id: out.id };
}
