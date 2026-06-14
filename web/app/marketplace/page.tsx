'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { api, type Agent, type MarketCandidate, type Recommendation } from '@/lib/api';
import { AgentDirectory } from '@/components/AgentDirectory';
import { MarketPicker } from '@/components/MarketPicker';
import { ResearchBrief } from '@/components/ResearchBrief';
import { FlowBanner } from '@/components/FlowBanner';
import { useUser } from '@/components/UserWallet';

const HOUSE_AGENT: Agent = {
  ens: 'house.honeybee.agent.eth',
  label: 'House',
  wallet_id: null,
  wallet_address: null,
  bankroll_usd: 1000,
  kelly_fraction: 0.25,
  confidence_floor: 0.55,
  venue: 'polymarket',
  llm_tier: 'router',
  x402_daily_usd: 5,
  paused: 0,
  created_at: 0,
};

function MarketplaceInner() {
  const u = useUser();
  const sp = useSearchParams();
  const marketParam = sp.get('market');

  const [agents, setAgents] = useState<Agent[]>([]);
  const [markets, setMarkets] = useState<MarketCandidate[]>([]);
  const [selectedAgent, setSelectedAgent] = useState(HOUSE_AGENT.ens);
  const [selectedMarket, setSelectedMarket] = useState('');
  const [hiring, setHiring] = useState(false);
  const [result, setResult] = useState<Recommendation | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.listAgents().then((a) => setAgents([HOUSE_AGENT, ...a])).catch(() => setAgents([HOUSE_AGENT]));
    api.topMarkets().then((m) => {
      setMarkets(m);
      const pick = marketParam && m.some((x) => x.market_id === marketParam) ? marketParam : m[0]?.market_id ?? '';
      setSelectedMarket(pick);
    }).catch(() => {});
  }, [marketParam]);

  const market = useMemo(
    () => markets.find((m) => m.market_id === selectedMarket),
    [markets, selectedMarket],
  );

  async function runResearch() {
    if (!u.address) {
      setErr('Connect a wallet in Settings before running research.');
      return;
    }
    if (!market) {
      setErr('Select a market to research.');
      return;
    }
    setHiring(true);
    setErr(null);
    setResult(null);
    try {
      const r = await api.hire({
        user_address: u.address,
        agent_ens: selectedAgent,
        venue: market.venue,
        market_id: market.market_id,
        price_usd: 0.05,
      });
      const errMsg = (r as unknown as { error?: string })?.error;
      if (errMsg || typeof r?.fair_price !== 'number') {
        setErr(errMsg ?? 'Agent found no edge on this market (low confidence or no trade).');
        return;
      }
      setResult(r);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Research failed');
    } finally {
      setHiring(false);
    }
  }

  return (
    <div className="space-y-8 px-6 py-6">
      <section>
        <h1 className="font-display text-2xl font-medium text-ink">Hire research</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">
          Choose an agent and market. You pay $0.05 USDC on Arc for a signed brief — the agent never touches your trading funds.
        </p>
      </section>

      {!u.address && (
        <FlowBanner
          message="Connect a wallet to run research."
          href="/settings"
          linkLabel="Connect wallet"
        />
      )}

      <div className="grid gap-8 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <h2 className="mb-3 text-xs font-medium uppercase tracking-widest text-ink-faint">Agents</h2>
          <AgentDirectory agents={agents} selectedEns={selectedAgent} onSelect={setSelectedAgent} />
        </div>

        <div className="lg:col-span-3">
          <div className="sticky top-4 space-y-4">
            <div className="card-terminal">
              <h2 className="text-xs font-medium uppercase tracking-widest text-ink-faint">Run research</h2>
              <p className="mt-1 font-mono text-xs text-gold/90">{selectedAgent}</p>

              <div className="mt-4">
                <label className="label">Market</label>
                <MarketPicker
                  markets={markets}
                  selectedId={selectedMarket}
                  onSelect={setSelectedMarket}
                />
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-ink/8 pt-4">
                <span className="text-sm text-ink-muted">
                  Cost <span className="font-medium text-ink">$0.05 USDC</span> on Arc
                </span>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={runResearch}
                  disabled={hiring || !u.address || !selectedMarket}
                >
                  {hiring ? 'Researching…' : 'Run research'}
                </button>
              </div>

              {err && (
                <p className="mt-3 rounded-lg bg-rose-600 px-3 py-2 text-sm font-semibold text-white">
                  {err}
                </p>
              )}
            </div>

            {result && (
              <ResearchBrief rec={result} animate inboxLink />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MarketplacePage() {
  return (
    <Suspense fallback={<div className="px-6 py-6 text-sm text-ink-muted">Loading…</div>}>
      <MarketplaceInner />
    </Suspense>
  );
}
