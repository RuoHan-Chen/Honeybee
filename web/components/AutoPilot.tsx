'use client';

/**
 * AutoPilot — hands-free execution when mode === 'auto'.
 *
 * The agent runs itself: it researches fresh markets and executes any
 * recommendation that fits your limits — per-trade cap AND remaining daily
 * budget — with no inbox approval. It stands down once the daily cap is hit.
 * Manual mode = this does nothing (every trade waits for approval).
 *
 * Renders nothing; mounted app-wide in the layout.
 */
import { useEffect, useRef } from 'react';
import { api } from '@/lib/api';
import { useUser } from './UserWallet';

const HOUSE = 'house.honeybee.agent.eth';
const TICK_MS = 15_000;

export function AutoPilot() {
  const u = useUser();
  const ticking = useRef(false);

  useEffect(() => {
    if (u.mode !== 'auto' || !u.address) return;
    let stopped = false;

    async function tick() {
      if (ticking.current) return;
      ticking.current = true;
      try {
        const recs = await api.listRecommendations({ limit: 100, user_address: u.address! });

        // Daily budget = limit minus what's already been executed.
        const executed = recs
          .filter((r) => r.status === 'executed')
          .reduce((s, r) => s + (r.suggested_size_usd || 0), 0);
        let remaining = u.dailyLimit - executed;
        if (remaining <= 0) return; // daily cap reached — stand down

        // 1) Auto-execute eligible pending recs (no manual approval).
        const pending = recs.filter((r) => r.status === 'pending');
        for (const r of pending) {
          if (stopped) return;
          const size = r.suggested_size_usd || 0;
          if (size > u.perTradeLimit || size > remaining) continue; // too big → leave for manual
          try {
            await api.approve(r.rec_id, {});
            remaining -= size;
          } catch {
            /* skip this one */
          }
          if (remaining <= 0) return;
        }

        // 2) Nothing to execute → research a fresh market so there's something
        //    to act on next tick. (No manual "hire" needed in auto mode.)
        if (!stopped && pending.length === 0) {
          const markets = await api.topMarkets().catch(() => []);
          const seen = new Set(recs.map((r) => r.market_id));
          const next = markets.find((m) => !seen.has(m.market_id));
          if (next) {
            await api
              .hire({ user_address: u.address!, agent_ens: HOUSE, venue: next.venue, market_id: next.market_id, price_usd: 0.05 })
              .catch(() => {}); // abstained / no edge — fine, try another next tick
          }
        }
      } finally {
        ticking.current = false;
      }
    }

    tick();
    const t = setInterval(tick, TICK_MS);
    return () => {
      stopped = true;
      clearInterval(t);
    };
  }, [u.mode, u.address, u.perTradeLimit, u.dailyLimit]);

  return null;
}
