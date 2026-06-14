'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api, Recommendation, MarketCandidate } from '@/lib/api';
import { useUser } from '@/components/UserWallet';

export default function Dashboard() {
  const u = useUser();
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [markets, setMarkets] = useState<MarketCandidate[]>([]);
  const [health, setHealth] = useState<{ ok: boolean; dry_run: boolean } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    async function load() {
      try {
        const [h, m, r] = await Promise.all([
          api.health(),
          api.topMarkets(),
          api.listRecommendations({ limit: 10, ...(u.address ? { user_address: u.address } : {}) }),
        ]);
        if (stop) return;
        setHealth(h); setMarkets(m); setRecs(r); setErr(null);
      } catch { if (!stop) setErr('offline'); }
    }
    load();
    const t = setInterval(load, 5000);
    return () => { stop = true; clearInterval(t); };
  }, [u.address]);

  return (
    <div className="space-y-8">
      <section className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <p className="mt-1 text-sm text-white/60">
            {health
              ? <>API <span className="pill-good">online</span> · mode{' '}
                  {health.dry_run ? <span className="pill-warn">PAPER</span> : <span className="pill-bad">LIVE</span>}{' '}
                  · exec <span className={u.mode === 'auto' ? 'pill-warn' : 'pill'}>{u.mode}</span></>
              : err ? <span className="pill-bad">offline — can’t reach the server</span>
              : 'connecting…'}
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/marketplace" className="btn-primary">Hire an agent</Link>
          <Link href="/trades" className="btn-ghost">View recommendations</Link>
        </div>
      </section>

      {!u.address && (
        <div className="card border-amber-500/30 bg-amber-500/5 text-sm text-amber-100">
          Connect a wallet to hire agents and approve trades. You can also browse the marketplace anonymously.
        </div>
      )}

      <section className="grid gap-6 lg:grid-cols-3">
        <div className="card">
          <div className="text-xs uppercase tracking-wider text-white/50">Your recommendations</div>
          <div className="mt-2 text-3xl font-semibold">{recs.length}</div>
          <div className="text-sm text-white/60">
            {recs.filter((r) => r.status === 'pending').length} pending · {recs.filter((r) => r.status === 'executed').length} executed
          </div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wider text-white/50">Markets being watched</div>
          <div className="mt-2 text-3xl font-semibold">{markets.length}</div>
          <div className="text-sm text-white/60">Long-tail candidates from live discovery</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wider text-white/50">Execution mode</div>
          <div className="mt-2 text-3xl font-semibold capitalize">{u.mode}</div>
          <div className="text-sm text-white/60">
            <Link href="/settings" className="underline">Change in settings →</Link>
          </div>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/60">Latest recommendations</h2>
          <div className="card space-y-3 p-4">
            {recs.length === 0 && (
              <div className="text-sm text-white/40">
                No recommendations yet. <Link href="/marketplace" className="text-honey-400 underline">Hire an agent →</Link>
              </div>
            )}
            {recs.slice(0, 6).map((r) => (
              <Link key={r.rec_id} href={`/trades?id=${r.rec_id}`}
                className="flex items-start justify-between gap-4 border-b border-white/5 pb-3 last:border-0 last:pb-0">
                <div className="min-w-0">
                  <div className="truncate text-sm">{r.market_question}</div>
                  <div className="mt-1 flex flex-wrap gap-2 text-xs text-white/50">
                    <span className="pill">{r.venue}</span>
                    <span>fair {r.fair_price.toFixed(3)}</span>
                    <span>mkt {r.market_price.toFixed(3)}</span>
                    <span className={r.edge > 0 ? 'text-emerald-400' : 'text-rose-400'}>
                      edge {r.edge > 0 ? '+' : ''}{r.edge.toFixed(3)}
                    </span>
                  </div>
                </div>
                <span className={
                  r.status === 'pending'   ? 'pill-warn' :
                  r.status === 'executed'  ? 'pill-good' :
                  r.status === 'rejected'  ? 'pill-bad'  : 'pill'
                }>{r.status}</span>
              </Link>
            ))}
          </div>
        </div>

        <div>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/60">Top candidate markets</h2>
          <div className="card space-y-3 p-4">
            {markets.length === 0 && <div className="text-sm text-white/40">No markets to show yet.</div>}
            {markets.slice(0, 8).map((m) => (
              <div key={m.market_id} className="flex items-start justify-between gap-3 border-b border-white/5 pb-3 last:border-0 last:pb-0">
                <div className="min-w-0">
                  <div className="truncate text-sm">{m.question}</div>
                  <div className="mt-1 flex flex-wrap gap-2 text-xs text-white/50">
                    <span className="pill">{m.venue}</span>
                    <span>vol24h ${m.volume_24h.toLocaleString()}</span>
                  </div>
                </div>
                <div className="shrink-0 text-right font-mono text-xs text-honey-400">{m.score.toFixed(2)}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
