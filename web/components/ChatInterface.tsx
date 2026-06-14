'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { api, type MarketCandidate, type Recommendation } from '@/lib/api';
import { ResearchBrief } from './ResearchBrief';
import { AgentPanel } from './AgentPanel';
import { PortfolioPanel } from './PortfolioPanel';
import { useChatShell } from './ChatShell';
import { useUser } from './UserWallet';

type ChatEntry =
  | { id: string; role: 'user'; text: string; ts: number }
  | { id: string; role: 'agent'; rec: Recommendation; ts: number }
  | { id: string; role: 'system'; text: string; ts: number };

const SUGGESTIONS = [
  'Scan for high-probability markets with short time to resolution',
  'Find non-sports markets above 90% with tight spreads',
  'Research a Fed rate cut market before June 2026',
];

const ACTION_PILLS = [
  { label: 'Market scanning', prompt: 'Scan for high-probability markets with short time to resolution' },
  { label: 'Market tracking', prompt: 'Track markets with the best execution conditions and tight spreads' },
  { label: 'Portfolio monitoring', prompt: 'Summarize my pending research and open positions' },
];

function matchMarket(prompt: string, markets: MarketCandidate[]): MarketCandidate | null {
  const words = prompt.toLowerCase().split(/\W+/).filter((w) => w.length > 3);
  if (words.length === 0) return markets[0] ?? null;

  let best: MarketCandidate | null = null;
  let bestScore = 0;
  for (const m of markets) {
    const q = m.question.toLowerCase();
    const score = words.reduce((s, w) => (q.includes(w) ? s + 1 : s), 0);
    if (score > bestScore) {
      bestScore = score;
      best = m;
    }
  }
  return bestScore > 0 ? best : markets[0] ?? null;
}

export function ChatInterface() {
  const u = useUser();
  const { selectedAgent, selectedAgentEns, recs, refreshRecs, pendingCount } = useChatShell();
  const [markets, setMarkets] = useState<MarketCandidate[]>([]);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<'adaptive' | 'deep' | 'fast'>('adaptive');
  const [busy, setBusy] = useState(false);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.topMarkets().then(setMarkets).catch(() => {});
  }, []);

  useEffect(() => {
    if (entries.length > 0) return;
    const seeded: ChatEntry[] = recs.slice(0, 3).map((r) => ({
      id: r.rec_id,
      role: 'agent' as const,
      rec: r,
      ts: r.ts,
    }));
    if (seeded.length === 0) {
      seeded.push({
        id: 'welcome',
        role: 'system',
        text: 'Ask your agent to scan markets, run research, or monitor your portfolio.',
        ts: Date.now(),
      });
    }
    setEntries(seeded.sort((a, b) => a.ts - b.ts));
  }, [recs, entries.length]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [entries, busy]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;

    const userEntry: ChatEntry = {
      id: `u-${Date.now()}`,
      role: 'user',
      text: trimmed,
      ts: Date.now(),
    };
    setEntries((prev) => [...prev, userEntry]);
    setInput('');
    setBusy(true);

    if (!u.address) {
      setEntries((prev) => [
        ...prev,
        {
          id: `s-${Date.now()}`,
          role: 'system',
          text: 'Connect your wallet in Settings before running research.',
          ts: Date.now(),
        },
      ]);
      setBusy(false);
      return;
    }

    const lower = trimmed.toLowerCase();
    if (lower.includes('portfolio') || lower.includes('pending') || lower.includes('position')) {
      const pending = recs.filter((r) => r.status === 'pending');
      const executed = recs.filter((r) => r.status === 'executed');
      setEntries((prev) => [
        ...prev,
        {
          id: `s-${Date.now()}`,
          role: 'system',
          text: `You have ${pending.length} pending brief${pending.length !== 1 ? 's' : ''} and ${executed.length} executed trade${executed.length !== 1 ? 's' : ''}. Check the portfolio panel on the right or open your inbox.`,
          ts: Date.now(),
        },
      ]);
      setBusy(false);
      return;
    }

    const market = matchMarket(trimmed, markets);
    if (!market) {
      setEntries((prev) => [
        ...prev,
        {
          id: `s-${Date.now()}`,
          role: 'system',
          text: 'No markets loaded yet — start the orchestrator or try again shortly.',
          ts: Date.now(),
        },
      ]);
      setBusy(false);
      return;
    }

    try {
      const r = await api.hire({
        user_address: u.address,
        agent_ens: selectedAgentEns,
        venue: market.venue,
        market_id: market.market_id,
        price_usd: 0.05,
      });
      const errMsg = (r as unknown as { error?: string })?.error;
      if (errMsg || typeof r?.fair_price !== 'number') {
        setEntries((prev) => [
          ...prev,
          {
            id: `s-${Date.now()}`,
            role: 'system',
            text: errMsg ?? `${selectedAgent.label} found no edge on "${market.question.slice(0, 60)}…"`,
            ts: Date.now(),
          },
        ]);
      } else {
        setEntries((prev) => [
          ...prev,
          { id: r.rec_id, role: 'agent', rec: r, ts: Date.now() },
        ]);
        await refreshRecs();
      }
    } catch (e: unknown) {
      setEntries((prev) => [
        ...prev,
        {
          id: `s-${Date.now()}`,
          role: 'system',
          text: e instanceof Error ? e.message : 'Research failed',
          ts: Date.now(),
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 px-6 py-5">
        <h1 className="text-lg font-medium text-ink">Find and act on market opportunities</h1>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4">
        <div className="mx-auto max-w-2xl space-y-4">
          {entries.map((e) => {
            if (e.role === 'user') {
              return (
                <div key={e.id} className="flex justify-end">
                  <p className="max-w-[85%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-sm leading-relaxed text-white">
                    {e.text}
                  </p>
                </div>
              );
            }
            if (e.role === 'system') {
              return (
                <p key={e.id} className="text-center text-sm text-ink-muted">
                  {e.text}
                  {!u.address && e.text.includes('Connect') && (
                    <>
                      {' '}
                      <Link href="/settings" className="text-agent hover:underline">
                        Connect wallet
                      </Link>
                    </>
                  )}
                </p>
              );
            }
            return (
              <div key={e.id} className="flex justify-start">
                <div className="max-w-full">
                  <p className="mb-2 text-xs font-medium text-agent">{selectedAgent.label}</p>
                  <ResearchBrief rec={e.rec} inboxLink={e.rec.status === 'pending'} />
                </div>
              </div>
            );
          })}
          {busy && (
            <div className="flex items-center gap-2 text-sm text-ink-muted">
              <span className="inline-flex gap-1">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-agent" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-agent [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-agent [animation-delay:300ms]" />
              </span>
              {selectedAgent.label} is researching…
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="shrink-0 border-t border-ink/8 bg-surface-panel px-6 py-5">
        <div className="mx-auto max-w-2xl lg:hidden">
          <div className="mb-4 overflow-hidden rounded-xl border border-ink/8 bg-white">
            <AgentPanel agent={selectedAgent} />
            <PortfolioPanel recs={recs} pendingCount={pendingCount} />
          </div>
        </div>
        <div className="mx-auto max-w-2xl">
          <div className="rounded-2xl border border-ink/10 bg-white shadow-sm shadow-black/[0.04]">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={3}
              placeholder="Ask your agent to scan markets, run research, or monitor your portfolio…"
              className="w-full resize-none rounded-t-2xl border-0 bg-transparent px-4 pb-2 pt-4 text-sm text-ink placeholder:text-ink-faint focus:outline-none focus:ring-0"
            />
            <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-agent/10 px-2.5 py-1 text-xs font-medium text-agent">
                  <span className="flex h-4 w-4 items-center justify-center rounded-full bg-agent text-[9px] text-white">
                    {selectedAgent.label.slice(0, 1)}
                  </span>
                  {selectedAgent.label}
                </span>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value as typeof mode)}
                  className="rounded-full border border-ink/10 bg-surface-sidebar px-2.5 py-1 text-xs text-ink-muted focus:outline-none"
                >
                  <option value="adaptive">Adaptive</option>
                  <option value="deep">Deep research</option>
                  <option value="fast">Fast scan</option>
                </select>
              </div>
              <button
                type="button"
                onClick={() => send(input)}
                disabled={busy || !input.trim()}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-ink text-white transition hover:bg-ink/90 disabled:opacity-40"
                aria-label="Send"
              >
                ↑
              </button>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {ACTION_PILLS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => setInput(p.prompt)}
                className="rounded-full border border-ink/10 bg-white px-3 py-1.5 text-xs text-ink-muted transition hover:border-agent/30 hover:text-ink"
              >
                {p.label}
              </button>
            ))}
          </div>

          <ul className="mt-4 space-y-1.5">
            {SUGGESTIONS.map((s) => (
              <li key={s}>
                <button
                  type="button"
                  onClick={() => setInput(s)}
                  className="text-left text-sm text-ink-faint transition hover:text-ink-muted"
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
