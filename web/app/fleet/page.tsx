'use client';
import { useEffect, useRef, useState } from 'react';
import { AdvancedLayout } from '@/components/AdvancedLayout';
import { walletApi, type FleetAgent, type Activity } from '@/lib/api';
import { balancesFor } from '@/lib/arc';

interface AgentWithBal extends FleetAgent {
  arcBalance?: number;
  usdcBalance?: number;
}

function kindBadge(kind: Activity['kind']): { label: string; color: string } {
  switch (kind) {
    case 'x402.required': return { label: '402',     color: 'bg-amber-500/15 text-amber-300' };
    case 'x402.paid':     return { label: 'PAID',    color: 'bg-emerald-500/15 text-emerald-300' };
    case 'x402.verified': return { label: 'SERVED',  color: 'bg-emerald-500/15 text-emerald-300' };
    case 'attestation':   return { label: 'ATTEST',  color: 'bg-sky-500/15 text-sky-300' };
    case 'agent.action':  return { label: 'AGENT',   color: 'bg-gold/15 text-gold-light' };
  }
}

function fmtTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString(undefined, { hour12: false });
}

function shortTx(hash?: string): string | null {
  if (!hash) return null;
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`;
}

export default function FleetPage() {
  const [fleet, setFleet] = useState<AgentWithBal[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  // Initial load: roster + balances.
  useEffect(() => {
    let cancelled = false;
    walletApi.fleet()
      .then(async (agents) => {
        if (cancelled) return;
        setFleet(agents);
        const withBal = await Promise.all(agents.map(async (a) => ({
          ...a, ...await balancesFor(a.address),
        })));
        if (!cancelled) setFleet(withBal);
      })
      .catch((e) => setErr(`fleet fetch failed: ${e.message}. Is the wallet service running on ${walletApi.baseUrl}?`));
    return () => { cancelled = true; };
  }, []);

  // Live activity stream.
  useEffect(() => {
    const es = walletApi.streamActivity();
    sourceRef.current = es;
    es.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data) as Activity;
        setActivity((prev) => {
          if (prev.some((p) => p.id === ev.id)) return prev;
          return [ev, ...prev].slice(0, 200);
        });
      } catch { /* ignore parse errors */ }
    };
    es.onerror = () => { /* let the browser auto-reconnect */ };
    return () => { es.close(); };
  }, []);

  // Periodically refresh balances (every 15s) so the UI reflects autonomous spending.
  useEffect(() => {
    const t = setInterval(async () => {
      setFleet((prev) => prev.length === 0 ? prev : prev);
      const next = await Promise.all((fleet ?? []).map(async (a) => ({
        ...a, ...await balancesFor(a.address),
      })));
      setFleet(next);
    }, 15_000);
    return () => clearInterval(t);
  }, [fleet.length]);

  return (
    <AdvancedLayout
      title="Agent fleet"
      description="Live view of on-chain agent wallets on Arc — identities, balances, and autonomous x402 payments plus attestations."
    >
      {err && <p className="rounded-lg border border-edge-no/30 bg-edge-no/10 px-3 py-2 text-sm text-rose-200">{err}</p>}

      <section className="grid gap-4 md:grid-cols-3">
        {fleet.map((a) => <AgentCard key={a.label} a={a} />)}
        {fleet.length === 0 && !err && (
          <div className="card text-sm text-white/60">Loading roster…</div>
        )}
      </section>

      <section className="card-terminal">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xs font-medium uppercase tracking-widest text-white/40">Live activity</h2>
          <div className="flex items-center gap-2 text-xs text-white/40">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
            streaming from {walletApi.baseUrl}
          </div>
        </div>
        {activity.length === 0 ? (
          <p className="text-sm text-white/40">
            No events yet. Start the autonomous loop with <code className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-xs">make agent-loop</code> in a separate terminal.
          </p>
        ) : (
          <ol className="space-y-1.5">
            {activity.map((ev) => {
              const b = kindBadge(ev.kind);
              const tx = shortTx(ev.details?.txHash as string | undefined);
              const explorer = ev.details?.explorer as string | undefined;
              return (
                <li key={ev.id} className="flex items-start gap-3 rounded-lg bg-white/[0.02] px-3 py-2 text-sm">
                  <span className={`mt-0.5 inline-block rounded px-1.5 py-0.5 font-mono text-[10px] ${b.color}`}>
                    {b.label}
                  </span>
                  <span className="font-mono text-[10px] text-white/40 tabular-nums">{fmtTime(ev.ts)}</span>
                  <span className="flex-1">{ev.summary}</span>
                  {tx && (
                    explorer
                      ? <a href={explorer} target="_blank" rel="noopener noreferrer"
                          className="font-mono text-[10px] text-gold hover:underline">{tx}</a>
                      : <span className="font-mono text-[10px] text-white/40">{tx}</span>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </AdvancedLayout>
  );
}

function AgentCard({ a }: { a: AgentWithBal }) {
  const ensName = a.ens?.name ?? `${a.label}.honeybee.agent`;
  return (
    <div className="card-terminal">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-semibold">{a.label}</div>
          {a.ens ? (
            <a
              href={a.ens.explorer}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-xs text-gold hover:underline"
              title={a.ens.verified
                ? `Resolves on Sepolia L1 → ${a.ens.resolvedAddress}`
                : `Not yet resolving on Sepolia L1 (resolved=${a.ens.resolvedAddress ?? 'null'})`}
            >
              {ensName}
            </a>
          ) : (
            <div className="font-mono text-xs text-gold">{ensName}</div>
          )}
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="pill">{a.role}</span>
          {a.ens?.verified && (
            <span
              className="inline-flex items-center gap-1 rounded bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-emerald-300"
              title="Subname resolves to this agent on Ethereum Sepolia L1"
            >
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
              ENS L1
            </span>
          )}
        </div>
      </div>
      <p className="mt-3 text-xs text-white/60">{a.description}</p>

      <div className="mt-4 grid grid-cols-2 gap-2 text-center text-xs">
        <div className="rounded-lg bg-white/5 py-2">
          <div className="text-base font-semibold tabular-nums">
            {a.arcBalance === undefined ? '—' : a.arcBalance.toFixed(4)}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-white/50">ARC</div>
        </div>
        <div className="rounded-lg bg-white/5 py-2">
          <div className="text-base font-semibold tabular-nums">
            {a.usdcBalance === undefined ? '—' : `$${a.usdcBalance.toFixed(3)}`}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-white/50">USDC</div>
        </div>
      </div>

      <div className="mt-3 space-y-0.5 text-[10px] text-white/40">
        <div>privy <span className="font-mono">{a.privyWalletId.slice(0, 8)}…</span></div>
        <div>addr  <a href={a.explorer?.address ?? '#'} target="_blank" rel="noopener noreferrer"
          className="font-mono text-gold hover:underline">{a.address.slice(0, 10)}…{a.address.slice(-6)}</a></div>
        <div>model <span className="font-mono">{a.model}</span></div>
      </div>
    </div>
  );
}
