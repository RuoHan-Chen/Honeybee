'use client';

interface Props {
  fair: number;
  market: number;
  className?: string;
}

export function ProbabilityBar({ fair, market, className = '' }: Props) {
  const fairPct = Math.max(0, Math.min(100, fair * 100));
  const mktPct = Math.max(0, Math.min(100, market * 100));
  const edge = fair - market;

  return (
    <div className={className}>
      <div className="relative h-2 overflow-hidden rounded-full bg-memo-ink/10">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-memo-muted/40"
          style={{ width: `${mktPct}%` }}
          title={`Market ${mktPct.toFixed(0)}%`}
        />
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${edge >= 0 ? 'bg-edge-yes' : 'bg-edge-no'}`}
          style={{ width: `${fairPct}%`, opacity: 0.85 }}
          title={`Fair ${fairPct.toFixed(0)}%`}
        />
        <div
          className="absolute top-0 h-full w-0.5 bg-memo-ink/60"
          style={{ left: `${mktPct}%` }}
        />
      </div>
      <div className="mt-2 flex justify-between font-mono text-[11px] text-memo-muted">
        <span>Market {(market * 100).toFixed(0)}%</span>
        <span className={edge >= 0 ? 'text-edge-yes' : 'text-edge-no'}>
          Fair {(fair * 100).toFixed(0)}% · edge {edge >= 0 ? '+' : ''}{(edge * 100).toFixed(1)}pp
        </span>
      </div>
    </div>
  );
}
