'use client';

import { useEffect, useState } from 'react';
import { AdvancedLayout } from '@/components/AdvancedLayout';
import { BlinkDeposit } from '@/components/BlinkDeposit';
import { walletApi, type FleetAgent } from '@/lib/api';

const PRESETS = [
  { id: 'base-sepolia-usdc', label: 'Base Sepolia · USDC (sandbox)', chainId: 84532,
    token: '0x036CbD53842c5426634e7929541eC2318f3dCF7e' },
  { id: 'sepolia-usdc', label: 'Sepolia · USDC (sandbox)', chainId: 11155111,
    token: '0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238' },
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
  const destination = agent?.address as `0x${string}` | undefined;

  return (
    <AdvancedLayout
      title="Fund via Blink"
      description="One-tap USDC deposit to agent wallets or your Polymarket funder."
    >
      {err && (
        <p className="rounded-lg bg-rose-600 px-3 py-2 text-sm font-semibold text-white">
          Could not load fleet: {err}
        </p>
      )}

      <div className="card-terminal mx-auto max-w-xl space-y-7 p-8">
        <label className="block">
          <span className="label">Destination token / chain</span>
          <select className="input" value={presetId} onChange={(e) => setPresetId(e.target.value)}>
            {PRESETS.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="label">Agent (deposit destination)</span>
          <select className="input" value={selected} onChange={(e) => setSelected(e.target.value)}>
            {fleet.length === 0 && <option value="">No agents found</option>}
            {fleet.map((a) => (
              <option key={a.address} value={a.address}>
                {a.label} — {a.address.slice(0, 8)}…{a.address.slice(-4)}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="label">Amount (USDC)</span>
          <input
            type="number"
            min={1}
            className="input"
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
          <p className="text-sm text-ink-muted">Select an agent.</p>
        )}

        {lastTransfer && (
          <p className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white">Transfer started: {lastTransfer}</p>
        )}
      </div>

      <p className="mx-auto max-w-xl text-xs text-white/40">
        Funds arrive as {preset.label} at{' '}
        {destination ? `${destination.slice(0, 10)}…` : 'the chosen address'}.
        Polygon USDC.e funds Polymarket directly; Base USDC funds the agent economy on Arc.
      </p>
    </AdvancedLayout>
  );
}
