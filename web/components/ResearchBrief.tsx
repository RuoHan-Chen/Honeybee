'use client';

import Link from 'next/link';
import type { Recommendation } from '@/lib/api';
import { ProbabilityBar } from './ProbabilityBar';

function fmt(n: number | null | undefined, digits: number): string {
  return typeof n === 'number' && Number.isFinite(n) ? n.toFixed(digits) : '—';
}

interface Props {
  rec: Recommendation;
  animate?: boolean;
  focused?: boolean;
  busy?: boolean;
  onApprove?: () => void;
  onReject?: () => void;
  inboxLink?: boolean;
}

export function ResearchBrief({
  rec,
  animate = false,
  focused = false,
  busy = false,
  onApprove,
  onReject,
  inboxLink = false,
}: Props) {
  const readonly = !onApprove && !onReject;

  return (
    <article
      id={`brief-${rec.rec_id}`}
      className={
        'memo-panel ' +
        (animate ? 'memo-animate ' : '') +
        (focused ? 'ring-2 ring-gold/40 ' : '')
      }
    >
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-memo-ink/10 pb-4">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-medium uppercase tracking-widest text-memo-muted">Research brief</p>
          <h3 className="mt-1 font-display text-lg font-medium leading-snug text-memo-ink">
            {rec.market_question}
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            <span className="rounded bg-memo-ink/8 px-2 py-0.5 font-mono text-[10px] uppercase text-memo-muted">
              {rec.venue}
            </span>
            <span className="rounded bg-memo-ink/8 px-2 py-0.5 font-mono text-[10px] text-memo-muted">
              {rec.agent_ens}
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-2xl font-medium tabular-nums text-memo-ink">
            ${fmt(rec.suggested_size_usd, 2)}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-memo-muted">Suggested size</div>
        </div>
      </header>

      <div className="mt-4">
        <ProbabilityBar fair={rec.fair_price} market={rec.market_price} />
      </div>

      <p className="mt-4 text-sm leading-relaxed text-memo-ink/85">{rec.rationale}</p>

      <dl className="mt-4 grid gap-2 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-memo-muted">Outcome</dt>
          <dd className="font-medium text-memo-ink">{rec.outcome} · {rec.side}</dd>
        </div>
        <div>
          <dt className="text-memo-muted">Confidence</dt>
          <dd className="font-mono font-medium text-memo-ink">{fmt(rec.confidence * 100, 0)}%</dd>
        </div>
        <div>
          <dt className="text-memo-muted">Status</dt>
          <dd className="font-medium capitalize text-memo-ink">{rec.status}</dd>
        </div>
      </dl>

      {(rec.research_hash || rec.research_attestation_tx) && (
        <footer className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-memo-ink/10 pt-3 font-mono text-[10px] text-memo-muted">
          {rec.research_hash && <span>hash {rec.research_hash.slice(0, 16)}…</span>}
          {rec.research_attestation_tx && (
            <span className="text-chain">attest {rec.research_attestation_tx.slice(0, 16)}…</span>
          )}
        </footer>
      )}

      {!readonly && (
        <div className="mt-5 flex flex-wrap gap-2">
          <button type="button" className="btn-memo" disabled={busy} onClick={onApprove}>
            {busy ? 'Submitting…' : 'Approve trade'}
          </button>
          <button type="button" className="btn-ghost border-memo-ink/20 text-memo-ink hover:bg-memo-ink/5" disabled={busy} onClick={onReject}>
            Reject
          </button>
        </div>
      )}

      {inboxLink && (
        <div className="mt-4">
          <Link href={`/inbox?id=${rec.rec_id}`} className="btn-memo text-sm">
            Open in inbox
          </Link>
        </div>
      )}
    </article>
  );
}
