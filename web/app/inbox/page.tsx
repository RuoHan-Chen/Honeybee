'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { api, type Recommendation } from '@/lib/api';
import { ResearchBrief } from '@/components/ResearchBrief';
import { FlowBanner } from '@/components/FlowBanner';
import { useUser } from '@/components/UserWallet';

function InboxInner() {
  const u = useUser();
  const sp = useSearchParams();
  const focusId = sp.get('id');
  const focusRef = useRef<HTMLDivElement>(null);

  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showExecuted, setShowExecuted] = useState(false);
  const [showRejected, setShowRejected] = useState(false);

  async function load() {
    try {
      const r = await api.listRecommendations({
        limit: 100,
        ...(u.address ? { user_address: u.address } : {}),
      });
      setRecs(r);
      setErr(null);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Could not load inbox');
    }
  }

  useEffect(() => {
    load();
  }, [u.address]);

  useEffect(() => {
    if (focusId && focusRef.current) {
      focusRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [focusId, recs]);

  async function approve(r: Recommendation) {
    setBusy(r.rec_id);
    setMsg(null);
    setErr(null);
    try {
      await api.approve(r.rec_id, {});
      setMsg('Trade submitted');
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Approval failed');
    } finally {
      setBusy(null);
    }
  }

  async function reject(r: Recommendation) {
    setBusy(r.rec_id);
    try {
      await api.reject(r.rec_id);
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Reject failed');
    } finally {
      setBusy(null);
    }
  }

  const pending = recs.filter((r) => r.status === 'pending');
  const executed = recs.filter((r) => r.status === 'executed');
  const rejected = recs.filter((r) => r.status === 'rejected');

  return (
    <div className="space-y-8 px-6 py-6">
      <section>
        <h1 className="font-display text-2xl font-medium text-ink">Inbox</h1>
        <p className="mt-2 text-sm text-ink-muted">
          {u.mode === 'manual'
            ? 'Review each research brief before a trade is sent to your prediction-market account.'
            : `Auto-execute is on — trades under $${u.perTradeLimit} per trade may fire without review.`}
        </p>
      </section>

      {u.mode === 'auto' && (
        <FlowBanner
          message="Auto-execute is enabled. Trades within your limits may submit without manual approval."
          href="/settings"
          linkLabel="Change in settings"
        />
      )}

      {msg && <p className="rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white">{msg}</p>}
      {err && <p className="rounded-lg bg-rose-600 px-4 py-2.5 text-sm font-semibold text-white">{err}</p>}

      <section>
        <h2 className="mb-4 text-xs font-medium uppercase tracking-widest text-ink-faint">
          Pending ({pending.length})
        </h2>
        {pending.length === 0 ? (
          <div className="card-terminal text-sm text-ink-muted">
            Nothing waiting.{' '}
            <Link href="/marketplace" className="text-gold hover:underline">
              Run research on a market
            </Link>
          </div>
        ) : (
          <div className="space-y-6">
            {pending.map((r) => (
              <div key={r.rec_id} ref={focusId === r.rec_id ? focusRef : undefined}>
                <ResearchBrief
                  rec={r}
                  focused={focusId === r.rec_id}
                  busy={busy === r.rec_id}
                  onApprove={() => approve(r)}
                  onReject={() => reject(r)}
                />
              </div>
            ))}
          </div>
        )}
      </section>

      {executed.length > 0 && (
        <section>
          <button
            type="button"
            className="mb-4 text-xs font-medium uppercase tracking-widest text-ink-faint hover:text-ink-muted"
            onClick={() => setShowExecuted((v) => !v)}
          >
            Executed ({executed.length}) {showExecuted ? '▾' : '▸'}
          </button>
          {showExecuted && (
            <div className="space-y-4 opacity-90">
              {executed.map((r) => (
                <ResearchBrief key={r.rec_id} rec={r} />
              ))}
            </div>
          )}
        </section>
      )}

      {rejected.length > 0 && (
        <section>
          <button
            type="button"
            className="mb-4 text-xs font-medium uppercase tracking-widest text-ink-faint hover:text-ink-muted"
            onClick={() => setShowRejected((v) => !v)}
          >
            Rejected ({rejected.length}) {showRejected ? '▾' : '▸'}
          </button>
          {showRejected && (
            <div className="space-y-4 opacity-75">
              {rejected.map((r) => (
                <ResearchBrief key={r.rec_id} rec={r} />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default function InboxPage() {
  return (
    <Suspense fallback={<div className="px-6 py-6 text-sm text-ink-muted">Loading…</div>}>
      <InboxInner />
    </Suspense>
  );
}
