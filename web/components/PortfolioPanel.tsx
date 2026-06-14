'use client';

import Link from 'next/link';
import type { Recommendation } from '@/lib/api';
import { useUser } from './UserWallet';

interface Props {
  recs: Recommendation[];
  pendingCount: number;
}

export function PortfolioPanel({ recs, pendingCount }: Props) {
  const u = useUser();

  const executed = recs.filter((r) => r.status === 'executed');
  const pending = recs.filter((r) => r.status === 'pending');
  const notional = executed.reduce((s, r) => s + (r.suggested_size_usd || 0), 0);
  const pendingNotional = pending.reduce((s, r) => s + (r.suggested_size_usd || 0), 0);

  return (
    <section className="border-b border-ink/8 p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Portfolio</h2>

      {!u.address ? (
        <p className="mt-3 text-sm leading-relaxed text-ink-muted">
          Connect a wallet to track positions and pending trades.
        </p>
      ) : (
        <>
          <div className="mt-3 rounded-xl border border-ink/8 bg-surface-panel p-3">
            <p className="text-[10px] font-medium uppercase tracking-wider text-ink-faint">Wallet</p>
            <p className="mt-1 font-mono text-xs text-ink">
              {u.address.slice(0, 8)}…{u.address.slice(-6)}
            </p>
          </div>

          <dl className="mt-3 grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-surface-sidebar px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-ink-faint">Open</dt>
              <dd className="font-mono text-lg font-medium tabular-nums text-ink">{executed.length}</dd>
            </div>
            <div className="rounded-lg bg-surface-sidebar px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-ink-faint">Pending</dt>
              <dd className="font-mono text-lg font-medium tabular-nums text-gold">{pendingCount}</dd>
            </div>
            <div className="rounded-lg bg-surface-sidebar px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-ink-faint">Deployed</dt>
              <dd className="font-mono text-sm font-medium tabular-nums text-ink">${notional.toFixed(0)}</dd>
            </div>
            <div className="rounded-lg bg-surface-sidebar px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-ink-faint">Awaiting</dt>
              <dd className="font-mono text-sm font-medium tabular-nums text-ink">${pendingNotional.toFixed(0)}</dd>
            </div>
          </dl>

          <p className="mt-3 text-[11px] text-ink-muted">
            Limits: ${u.perTradeLimit}/trade · ${u.dailyLimit}/day
          </p>
        </>
      )}

      {pendingCount > 0 && (
        <Link
          href="/inbox"
          className="mt-3 flex w-full items-center justify-center rounded-lg border border-gold/30 bg-gold/10 px-3 py-2 text-xs font-medium text-gold-dark hover:bg-gold/15"
        >
          Review {pendingCount} pending brief{pendingCount > 1 ? 's' : ''}
        </Link>
      )}

      {executed.length > 0 && (
        <ul className="mt-4 max-h-40 space-y-2 overflow-y-auto">
          {executed.slice(0, 5).map((r) => (
            <li key={r.rec_id} className="rounded-lg border border-ink/6 bg-surface-panel px-3 py-2">
              <p className="line-clamp-2 text-xs leading-snug text-ink">{r.market_question}</p>
              <p className="mt-1 font-mono text-[10px] text-ink-muted">
                {r.side} {r.outcome} · ${r.suggested_size_usd.toFixed(2)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
