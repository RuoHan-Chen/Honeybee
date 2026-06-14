'use client';

import { useEffect, useMemo, useState } from 'react';
import type { MarketCandidate } from '@/lib/api';

interface Props {
  markets: MarketCandidate[];
  selectedId: string;
  onSelect: (id: string) => void;
}

export function MarketPicker({ markets, selectedId, onSelect }: Props) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return markets;
    return markets.filter(
      (m) =>
        m.question.toLowerCase().includes(q) ||
        m.venue.toLowerCase().includes(q) ||
        m.market_id.toLowerCase().includes(q),
    );
  }, [markets, query]);

  if (markets.length === 0) {
    return (
      <p className="rounded-lg border border-white/[0.06] bg-midnight/50 px-4 py-6 text-sm text-white/45">
        No markets yet. Discovery runs every few minutes — check back shortly.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <input
        type="search"
        className="input"
        placeholder="Search markets…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <ul className="max-h-64 space-y-1 overflow-y-auto rounded-lg border border-white/[0.06] bg-midnight/40 p-1">
        {filtered.length === 0 && (
          <li className="px-3 py-4 text-center text-sm text-white/40">No matches</li>
        )}
        {filtered.map((m) => {
          const active = m.market_id === selectedId;
          return (
            <li key={m.market_id}>
              <button
                type="button"
                onClick={() => onSelect(m.market_id)}
                className={
                  'w-full rounded-lg px-3 py-2.5 text-left text-sm transition ' +
                  (active ? 'bg-gold/15 text-white ring-1 ring-gold/30' : 'text-white/75 hover:bg-white/[0.04]')
                }
              >
                <span className="line-clamp-2">{m.question}</span>
                <span className="mt-1 flex flex-wrap gap-2 font-mono text-[10px] text-white/45">
                  <span>{m.venue}</span>
                  <span>vol ${m.volume_24h.toLocaleString()}</span>
                  <span>score {m.score.toFixed(2)}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
