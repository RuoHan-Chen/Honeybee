'use client';

/**
 * Fund an agent via Blink — one-tap USDC deposit into the selected agent's
 * on-chain wallet. Destination address is pulled live from the fleet roster
 * (no hard-coded values).
 */
import { useEffect, useState } from 'react';

import { BlinkDeposit } from '@/components/BlinkDeposit';
import { walletApi, type FleetAgent } from '@/lib/api';

export default function DepositPage() {
  const [fleet, setFleet] = useState<FleetAgent[]>([]);
  const [selected, setSelected] = useState<string>('');
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

  return (
    <main className="mx-auto max-w-xl px-6 py-10">
      <h1 className="text-2xl font-semibold text-honey-300">Fund an agent</h1>
      <p className="mt-2 text-sm text-zinc-400">
        One-tap USDC deposit via Blink, straight into the agent&apos;s wallet — no bridging,
        no leaving the app. Signing happens server-side; the merchant key never hits the browser.
      </p>

      {err && <p className="mt-4 text-rose-400 text-sm">Could not load fleet: {err}</p>}

      <div className="mt-6 space-y-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
        <label className="block text-sm text-zinc-300">
          Agent
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
          Amount (USDC)
          <input
            type="number"
            min={1}
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
            value={amount}
            onChange={(e) => setAmount(Math.max(1, Number(e.target.value)))}
          />
        </label>

        {agent ? (
          <BlinkDeposit
            address={agent.address}
            amount={amount}
            onDeposited={(id) => setLastTransfer(id)}
          />
        ) : (
          <p className="text-sm text-zinc-500">Select an agent to deposit.</p>
        )}

        {lastTransfer && (
          <p className="text-emerald-300 text-sm">Transfer started: {lastTransfer}</p>
        )}
      </div>

      <p className="mt-4 text-xs text-zinc-500">
        Funds land as USDC on Base ({selected ? `${selected.slice(0, 10)}…` : 'the agent address'}).
        The agent can then settle x402 payments / bridge to Arc for the agent economy.
      </p>
    </main>
  );
}
