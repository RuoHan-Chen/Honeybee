'use client';
import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { api, Recommendation } from '@/lib/api';
import { useUser } from '@/components/UserWallet';

function TradesInner() {
  const u = useUser();
  const sp = useSearchParams();
  const focusId = sp.get('id');
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      const r = await api.listRecommendations({
        limit: 100, ...(u.address ? { user_address: u.address } : {}),
      });
      setRecs(r);
    } catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { load(); }, [u.address]);

  async function approve(r: Recommendation) {
    setBusy(r.rec_id); setMsg(null); setErr(null);
    try {
      // In production: pull broker creds from user's vault. Empty here = paper.
      const res = await api.approve(r.rec_id, {});
      setMsg(
        `Executed ${r.outcome} @ ${res.fill.avg_price.toFixed(3)} · size $${res.fill.filled_usd.toFixed(2)} · ` +
        `trade attest tx ${res.attestation.tx_hash.slice(0, 12)}…`
      );
      await load();
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(null); }
  }

  async function reject(r: Recommendation) {
    setBusy(r.rec_id);
    try { await api.reject(r.rec_id); await load(); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(null); }
  }

  const grouped = {
    pending:  recs.filter((r) => r.status === 'pending'),
    executed: recs.filter((r) => r.status === 'executed'),
    rejected: recs.filter((r) => r.status === 'rejected'),
    other:    recs.filter((r) => !['pending', 'executed', 'rejected'].includes(r.status)),
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Recommendations</h1>
        <p className="mt-1 text-sm text-white/60">
          Agent-signed research artifacts. {u.mode === 'manual'
            ? <>You approve before any trade is sent to your prediction-market account.</>
            : <>Auto-execute is ON, up to your per-trade limit (${u.perTradeLimit}).</>}
        </p>
      </div>

      {msg && <div className="rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">{msg}</div>}
      {err && <div className="rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{err}</div>}

      <Group title={`Pending (${grouped.pending.length})`}>
        {grouped.pending.length === 0 && <Empty>No pending recommendations. Hire an agent from the marketplace.</Empty>}
        {grouped.pending.map((r) => (
          <RecCard key={r.rec_id} r={r} focused={focusId === r.rec_id} busy={busy === r.rec_id}
            onApprove={() => approve(r)} onReject={() => reject(r)} />
        ))}
      </Group>

      <Group title={`Executed (${grouped.executed.length})`}>
        {grouped.executed.length === 0 && <Empty>No executed trades yet.</Empty>}
        {grouped.executed.map((r) => <RecCard key={r.rec_id} r={r} readonly />)}
      </Group>

      {grouped.rejected.length > 0 && (
        <Group title={`Rejected (${grouped.rejected.length})`}>
          {grouped.rejected.map((r) => <RecCard key={r.rec_id} r={r} readonly />)}
        </Group>
      )}
    </div>
  );
}

// useSearchParams must sit under a Suspense boundary for the App Router build.
export default function Trades() {
  return (
    <Suspense fallback={null}>
      <TradesInner />
    </Suspense>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/60">{title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="card text-sm text-white/40">{children}</div>;
}

function RecCard({ r, focused, busy, readonly, onApprove, onReject }: {
  r: Recommendation; focused?: boolean; busy?: boolean; readonly?: boolean;
  onApprove?: () => void; onReject?: () => void;
}) {
  return (
    <div className={
      'card ' + (focused ? 'border-honey-500/60 ring-1 ring-honey-500/40' : '')
    }>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium">{r.market_question}</div>
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-white/50">
            <span className="pill">{r.venue}</span>
            <span className="pill">{r.agent_ens}</span>
            <span>fair <b className="text-white">{r.fair_price.toFixed(3)}</b></span>
            <span>mkt {r.market_price.toFixed(3)}</span>
            <span className={r.edge >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
              edge {r.edge >= 0 ? '+' : ''}{r.edge.toFixed(3)}
            </span>
            <span>conf {(r.confidence * 100).toFixed(0)}%</span>
          </div>
          <p className="mt-2 max-w-3xl text-xs text-white/70">{r.rationale}</p>
          <div className="mt-2 flex flex-wrap gap-4 font-mono text-[10px] text-white/40">
            <span>research_hash {r.research_hash.slice(0, 18)}…</span>
            {r.research_attestation_tx && <span>attest {r.research_attestation_tx.slice(0, 18)}…</span>}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-2xl font-semibold">${r.suggested_size_usd.toFixed(2)}</div>
          <div className="text-xs text-white/50">suggested size</div>
        </div>
      </div>
      {!readonly && (
        <div className="mt-4 flex gap-2">
          <button className="btn-primary" disabled={busy} onClick={onApprove}>
            {busy ? 'Submitting…' : `Approve · BUY ${r.outcome}`}
          </button>
          <button className="btn-ghost" disabled={busy} onClick={onReject}>Reject</button>
        </div>
      )}
    </div>
  );
}
