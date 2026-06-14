'use client';

/**
 * Fund via Blink — one-tap USDC deposit.
 *
 * Two presets:
 *   - Base · USDC          → funds an agent's wallet for the agent economy (x402/Arc)
 *   - Polygon · USDC.e     → funds the Polymarket trading wallet directly
 *                            (Polymarket uses USDC.e 0x2791…, which Blink delivers)
 *
 * Destination defaults to the selected agent's on-chain address (pulled live
 * from the fleet roster — no hard-coded values); override with a custom address
 * to target your Polymarket funder.
 */
import { useEffect, useState } from 'react';

import { BlinkDeposit } from '@/components/BlinkDeposit';
import { walletApi, type FleetAgent } from '@/lib/api';

const PRESETS = [
  { id: 'base-usdc', label: 'Base · USDC (agent economy)', chainId: 8453,
    token: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913' },
  { id: 'polygon-usdce', label: 'Polygon · USDC.e (Polymarket trading)', chainId: 137,
    token: '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174' },
  { id: 'polygon-usdc', label: 'Polygon · USDC (native)', chainId: 137,
    token: '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359' },
] as const;

export default function DepositPage() {
  const [fleet, setFleet] = useState<FleetAgent[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [presetId, setPresetId] = useState<string>(PRESETS[0].id);
  const [custom, setCustom] = useState<string>('');
  const [amount, setAmount] = useState<number>(5);
  const [err, setErr] = useState<string | null>(null);
  const [lastTransfer, setLastTransfer] = useState<string | null>(null);

  useEffect(() => {
    walletApi
      .fleet()
      .then((f) => {
        setFleet(f);
        if (f[0]) setSelected(f[0].address);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  const agent = fleet.find((a) => a.address === selected);
  const preset = PRESETS.find((p) => p.id === presetId)!;
  const customValid = /^0x[a-fA-F0-9]{40}$/.test(custom.trim());
  const destination = (customValid ? custom.trim() : agent?.address) as `0x${string}` | undefined;

  return (
    <main className="mx-auto max-w-xl px-6 py-10">
      <h1 className="text-2xl font-semibold text-honey-300">Fund via Blink</h1>
      <p className="mt-2 text-sm text-zinc-400">
        One-tap USDC deposit — no bridging, no leaving the app. Signing happens server-side;
        the merchant key never hits the browser.
      </p>

      {err && <p className="mt-4 text-rose-400 text-sm">Could not load fleet: {err}</p>}

      <div className="mt-6 space-y-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
        <label className="block text-sm text-zinc-300">
          Destination token / chain
          <select
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
            value={presetId}
            onChange={(e) => setPresetId(e.target.value)}
          >
            {PRESETS.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
        </label>

        <label className="block text-sm text-zinc-300">
          Agent (deposit destination)
          <select
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            {fleet.length === 0 && <option value="">No agents found</option>}
            {fleet.map((a) => (
              <option key={a.address} value={a.address}>
                {a.label} — {a.address.slice(0, 8)}…{a.address.slice(-4)}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm text-zinc-300">
          …or custom address (e.g. your Polymarket funder)
          <input
            placeholder="0x…"
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-zinc-100"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
          />
          {custom && !customValid && <span className="text-rose-400 text-xs">not a valid 0x address</span>}
        </label>

        <label className="block text-sm text-zinc-300">
          Amount (USDC)
          <input
            type="number"
            min={1}
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
            value={amount}
            onChange={(e) => setAmount(Math.max(1, Number(e.target.value)))}
          />
        </label>

        {destination ? (
          <BlinkDeposit
            address={destination}
            amount={amount}
            chainId={preset.chainId}
            token={preset.token}
            onDeposited={(id) => setLastTransfer(id)}
          />
        ) : (
          <p className="text-sm text-zinc-500">Select an agent or enter a destination address.</p>
        )}

        {lastTransfer && <p className="text-emerald-300 text-sm">Transfer started: {lastTransfer}</p>}
      </div>

      <p className="mt-4 text-xs text-zinc-500">
        Funds land as {preset.label} at {destination ? `${destination.slice(0, 10)}…` : 'the chosen address'}.
        Polygon · USDC.e funds Polymarket trading directly; Base · USDC funds the agent economy (bridge to Arc).
      </p>
    </main>
  );
}
