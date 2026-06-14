'use client';

import Link from 'next/link';
import { useUser } from './UserWallet';

interface Props {
  pendingCount: number;
  executedCount: number;
  hasRecommendations: boolean;
}

type Stage = 'done' | 'current' | 'pending';

function stageStatus(step: number, wallet: boolean, hired: boolean, pending: number, executed: number): Stage {
  if (step === 0) return wallet ? 'done' : 'current';
  if (step === 1) {
    if (!wallet) return 'pending';
    return hired ? 'done' : 'current';
  }
  if (step === 2) {
    if (!wallet) return 'pending';
    if (pending > 0) return 'current';
    return hired || executed > 0 ? 'done' : 'pending';
  }
  if (step === 3) {
    if (executed > 0) return 'done';
    if (pending > 0) return 'pending';
    return 'pending';
  }
  return 'pending';
}

const STAGES = [
  { label: 'Connect wallet', href: '/settings', detail: (w: boolean) => (w ? 'Connected' : 'Required to hire') },
  { label: 'Hire research', href: '/marketplace', detail: () => 'Pick agent + market' },
  { label: 'Review inbox', href: '/inbox', detail: (w: boolean, _h: boolean, p: number) => (p > 0 ? `${p} pending` : 'Nothing waiting') },
  { label: 'Trade executed', href: '/inbox', detail: (_w: boolean, _h: boolean, _p: number, e: number) => (e > 0 ? `${e} completed` : '—') },
] as const;

export function PipelineBoard({ pendingCount, executedCount, hasRecommendations }: Props) {
  const u = useUser();
  const wallet = !!u.address;

  return (
    <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {STAGES.map((stage, i) => {
        const status = stageStatus(i, wallet, hasRecommendations, pendingCount, executedCount);
        const detail = stage.detail(wallet, hasRecommendations, pendingCount, executedCount);
        return (
          <li key={stage.label}>
            <Link
              href={stage.href}
              className={
                'block rounded-xl border p-4 transition ' +
                (status === 'current'
                  ? 'border-gold/40 bg-gold/5 ring-1 ring-gold/20'
                  : status === 'done'
                    ? 'border-edge-yes/30 bg-edge-yes/5 hover:border-edge-yes/50'
                    : 'border-white/[0.06] bg-slate/50 hover:border-white/10')
              }
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-white/90">{stage.label}</span>
                <span
                  className={
                    'h-2 w-2 shrink-0 rounded-full ' +
                    (status === 'done' ? 'bg-edge-yes' : status === 'current' ? 'bg-gold' : 'bg-white/20')
                  }
                />
              </div>
              <p className="mt-1 text-xs text-white/50">{detail}</p>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
