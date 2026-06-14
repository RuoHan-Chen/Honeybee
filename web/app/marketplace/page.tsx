'use client';
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { api, Agent, MarketCandidate, Recommendation } from '@/lib/api';
import { useUser } from '@/components/UserWallet';

/** Safe `.toFixed` for values that might be undefined/null (e.g. backend
 *  returned a partial recommendation or an error envelope). */
function fmt(n: number | null | undefined, digits: number): string {
  return typeof n === 'number' && Number.isFinite(n) ? n.toFixed(digits) : '—';
}

const HOUSE_AGENT: Agent = {
  ens: 'house.honeybee.agent.eth',
  label: 'House',
  wallet_id: null, wallet_address: null,
  bankroll_usd: 1000, kelly_fraction: 0.25, confidence_floor: 0.55,
  venue: 'polymarket', llm_tier: 'router', x402_daily_usd: 5, paused: 0, created_at: 0,
};

export default function Marketplace() {
  const u = useUser();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [markets, setMarkets] = useState<MarketCandidate[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string>(HOUSE_AGENT.ens);
  const [selectedMarket, setSelectedMarket] = useState<string>('');
  const [hiring, setHiring] = useState(false);
  const [result, setResult] = useState<Recommendation | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.listAgents().then((a) => setAgents([HOUSE_AGENT, ...a])).catch(() => setAgents([HOUSE_AGENT]));
    api.topMarkets().then((m) => {
      setMarkets(m);
      if (m[0]) setSelectedMarket(m[0].market_id);
    }).catch(() => {});
  }, []);

  const market = useMemo(() => markets.find((m) => m.market_id === selectedMarket), [markets, selectedMarket]);

  async function hire() {
    if (!u.address) { setErr('Connect a wallet first'); return; }
    if (!market) { setErr('Pick a market'); return; }
    setHiring(true); setErr(null); setResult(null);
    try {
      const r = await api.hire({
        user_address: u.address,
        agent_ens: selectedAgent,
        venue: market.venue,
        market_id: market.market_id,
        price_usd: 0.05,
      });
      // The backend returns either a full Recommendation or {error: "..."}.
      // Without a real recommendation we have no fair_price etc. to render.
      const errMsg = (r as unknown as { error?: string })?.error;
      if (errMsg || typeof r?.fair_price !== 'number') {
        setErr(errMsg ?? 'Agent returned no recommendation (no edge / low confidence).');
        return;
      }
      setResult(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setHiring(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Marketplace</h1>
        <p className="mt-1 text-sm text-white/60">
          Hire an agent (paid via <span className="text-honey-400">x402</span> on Arc) to research any market.
          The agent never touches your funds — it returns a signed recommendation you approve or reject.
        </p>
      </div>

      <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {agents.map((a) => (
          <AgentCard key={a.ens} agent={a}
            selected={selectedAgent === a.ens}
            onSelect={() => setSelectedAgent(a.ens)} />
        ))}
      </section>

      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-white/60">Hire</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="label">Agent</label>
            <div className="input bg-ink-900 font-mono text-xs">{selectedAgent}</div>
          </div>
          <div>
            <label className="label">Market</label>
            <select className="input" value={selectedMarket}
              onChange={(e) => setSelectedMarket(e.target.value)}>
              {markets.length === 0 && <option value="">No markets discovered yet</option>}
              {markets.map((m) => (
                <option key={m.market_id} value={m.market_id}>
                  [{m.venue}] {m.question.length > 80 ? m.question.slice(0, 80) + '…' : m.question}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-center justify-between rounded-lg bg-ink-900/60 px-4 py-3 text-sm">
          <span className="text-white/60">Cost: <b className="text-white">$0.05 USDC on Arc</b> via x402</span>
          <button className="btn-primary" onClick={hire} disabled={hiring || !u.address || !selectedMarket}>
            {hiring ? 'Researching…' : 'Hire agent ($0.05)'}
          </button>
        </div>
        {!u.address && <p className="text-xs text-amber-300">Connect a wallet to hire.</p>}
        {err && <p className="rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{err}</p>}

        {result && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 text-sm">
            <div className="mb-2 font-semibold text-emerald-300">Recommendation ready</div>
            <div className="grid gap-1 text-xs text-white/80">
              <div><b>{result.market_question}</b></div>
              <div>Outcome: <b>{result.outcome}</b> · side {result.side}</div>
              <div>
                Fair {fmt(result.fair_price, 3)} · Mkt {fmt(result.market_price, 3)} · edge{' '}
                <b className={(result.edge ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  {(result.edge ?? 0) >= 0 ? '+' : ''}{fmt(result.edge, 3)}
                </b>
              </div>
              <div>
                Confidence {fmt((result.confidence ?? 0) * 100, 0)}% · suggested size ${fmt(result.suggested_size_usd, 2)}
              </div>
              {result.research_hash && (
                <div className="mt-1 font-mono text-[10px] text-white/40">research_hash {result.research_hash.slice(0, 18)}…</div>
              )}
              {result.research_attestation_tx && (
                <div className="font-mono text-[10px] text-white/40">attest tx {result.research_attestation_tx.slice(0, 18)}…</div>
              )}
            </div>
            <div className="mt-3">
              <Link href={`/trades?id=${result.rec_id}`} className="btn-primary">Review & approve →</Link>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function AgentCard({ agent, selected, onSelect }:
  { agent: Agent; selected: boolean; onSelect: () => void }) {
  const [rep, setRep] = useState<{ recommendations: number; executed_trades: number; resolutions_anchored: number } | null>(null);
  useEffect(() => { api.reputation(agent.ens).then(setRep).catch(() => {}); }, [agent.ens]);

  return (
    <button onClick={onSelect}
      className={
        'card text-left transition ' +
        (selected ? 'border-honey-500/60 ring-1 ring-honey-500/40' : 'hover:border-honey-500/30')
      }>
      <div className="flex items-start justify-between">
        <div>
          <div className="font-semibold">{agent.label}</div>
          <div className="font-mono text-xs text-honey-400">{agent.ens}</div>
        </div>
        <span className="pill">{agent.venue}</span>
      </div>
      <p className="mt-3 text-xs text-white/60">
        LLM tier <b>{agent.llm_tier}</b> · Kelly <b>{agent.kelly_fraction}</b> · floor <b>{agent.confidence_floor}</b>
      </p>
      {rep && (
        <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
          <div className="rounded-lg bg-white/5 py-2">
            <div className="text-base font-semibold">{rep.recommendations}</div>
            <div className="text-[10px] uppercase tracking-wider text-white/50">recs</div>
          </div>
          <div className="rounded-lg bg-white/5 py-2">
            <div className="text-base font-semibold">{rep.executed_trades}</div>
            <div className="text-[10px] uppercase tracking-wider text-white/50">trades</div>
          </div>
          <div className="rounded-lg bg-white/5 py-2">
            <div className="text-base font-semibold">{rep.resolutions_anchored}</div>
            <div className="text-[10px] uppercase tracking-wider text-white/50">resolved</div>
          </div>
        </div>
      )}
    </button>
  );
}
