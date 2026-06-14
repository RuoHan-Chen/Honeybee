'use client';

import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { api, type Agent, type Recommendation } from '@/lib/api';
import { AgentPanel } from './AgentPanel';
import { PortfolioPanel } from './PortfolioPanel';
import { useUser } from './UserWallet';

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

interface ChatShellState {
  agents: Agent[];
  selectedAgentEns: string;
  setSelectedAgentEns: (ens: string) => void;
  selectedAgent: Agent;
  recs: Recommendation[];
  pendingCount: number;
  refreshRecs: () => Promise<void>;
  search: string;
  setSearch: (q: string) => void;
}

const ChatCtx = createContext<ChatShellState | null>(null);

export function useChatShell(): ChatShellState {
  const c = useContext(ChatCtx);
  if (!c) throw new Error('useChatShell must be used inside ChatShell');
  return c;
}

const railLinks = [
  { href: '/', label: 'Chat', icon: '⌂' },
  { href: '/marketplace', label: 'Hire', icon: '⊞' },
  { href: '/inbox', label: 'Inbox', icon: '☰' },
  { href: '/settings', label: 'Settings', icon: '⚙' },
];

const ADVANCED_PATHS = ['/fleet', '/deposit'];

function IconRail({ pending }: { pending: number }) {
  const path = usePathname();

  return (
    <nav className="flex w-14 shrink-0 flex-col items-center border-r border-black/10 bg-rail py-4 text-white/70">
      <Link href="/" className="mb-6 flex h-9 w-9 items-center justify-center rounded-lg text-lg text-gold" title="Honeybee">
        🐝
      </Link>
      {railLinks.map((l) => {
        const active = path === l.href || (l.href !== '/' && path?.startsWith(l.href));
        const isInbox = l.href === '/inbox';
        return (
          <Link
            key={l.href}
            href={l.href}
            title={l.label}
            className={
              'relative mb-2 flex h-10 w-10 items-center justify-center rounded-xl text-base transition ' +
              (active ? 'bg-white/15 text-white' : 'hover:bg-white/10 hover:text-white')
            }
          >
            {l.icon}
            {isInbox && pending > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-gold px-1 text-[9px] font-bold text-midnight">
                {pending > 9 ? '9+' : pending}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

function Sidebar() {
  const { agents, selectedAgentEns, setSelectedAgentEns, recs, search, setSearch } = useChatShell();

  const filteredAgents = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter(
      (a) => a.label.toLowerCase().includes(q) || a.ens.toLowerCase().includes(q),
    );
  }, [agents, search]);

  const threads = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = [...recs].sort((a, b) => b.ts - a.ts);
    if (!q) return list.slice(0, 12);
    return list.filter((r) => r.market_question.toLowerCase().includes(q)).slice(0, 12);
  }, [recs, search]);

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-ink/8 bg-surface-sidebar">
      <div className="border-b border-ink/8 px-4 py-4">
        <div className="flex items-center justify-between gap-2">
          <span className="font-display text-lg font-medium text-ink">Honeybee</span>
          <Link
            href="/marketplace"
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-ink/10 text-sm text-ink-muted hover:bg-surface-panel"
            title="New research"
          >
            +
          </Link>
        </div>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search agents & chats"
          className="chat-input mt-3"
        />
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        <p className="px-2 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">Agents</p>
        <ul className="mt-2 space-y-0.5">
          {filteredAgents.map((a) => {
            const active = a.ens === selectedAgentEns;
            return (
              <li key={a.ens}>
                <button
                  type="button"
                  onClick={() => setSelectedAgentEns(a.ens)}
                  className={
                    'flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-sm transition ' +
                    (active ? 'bg-agent/10 text-ink' : 'text-ink-muted hover:bg-surface-panel hover:text-ink')
                  }
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-agent/15 text-[11px] font-semibold text-agent">
                    {a.label.slice(0, 1)}
                  </span>
                  <span className="truncate">{a.label}</span>
                </button>
              </li>
            );
          })}
        </ul>

        <p className="mt-5 px-2 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">Chats</p>
        <ul className="mt-2 space-y-0.5">
          {threads.length === 0 && (
            <li className="px-2 py-2 text-xs text-ink-faint">No research threads yet.</li>
          )}
          {threads.map((r) => (
            <li key={r.rec_id}>
              <Link
                href={`/inbox?id=${r.rec_id}`}
                className="block truncate rounded-lg px-2 py-2 text-sm text-ink-muted hover:bg-surface-panel hover:text-ink"
              >
                {r.market_question}
              </Link>
            </li>
          ))}
        </ul>
      </div>

      <div className="border-t border-ink/8 px-4 py-3 text-[11px] text-ink-faint">
        <Link href="/fleet" className="hover:text-agent">Fleet</Link>
        {' · '}
        <Link href="/deposit" className="hover:text-agent">Fund</Link>
      </div>
    </aside>
  );
}

export function ChatShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const u = useUser();
  const [agents, setAgents] = useState<Agent[]>([HOUSE_AGENT]);
  const [selectedAgentEns, setSelectedAgentEns] = useState(HOUSE_AGENT.ens);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [search, setSearch] = useState('');
  const [modeChip, setModeChip] = useState<string | null>(null);

  const showRightPanel = !ADVANCED_PATHS.some((p) => path?.startsWith(p));
  const selectedAgent = agents.find((a) => a.ens === selectedAgentEns) ?? HOUSE_AGENT;
  const pendingCount = recs.filter((r) => r.status === 'pending').length;

  async function refreshRecs() {
    try {
      const r = await api.listRecommendations({
        limit: 50,
        ...(u.address ? { user_address: u.address } : {}),
      });
      setRecs(r);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    api.listAgents()
      .then((a) => setAgents([HOUSE_AGENT, ...a]))
      .catch(() => setAgents([HOUSE_AGENT]));
    api.health().then((h) => setModeChip(h.dry_run ? 'Paper' : 'Live')).catch(() => setModeChip(null));
  }, []);

  useEffect(() => {
    refreshRecs();
    const t = setInterval(refreshRecs, 15000);
    return () => clearInterval(t);
  }, [u.address]);

  const ctx: ChatShellState = {
    agents,
    selectedAgentEns,
    setSelectedAgentEns,
    selectedAgent,
    recs,
    pendingCount,
    refreshRecs,
    search,
    setSearch,
  };

  return (
    <ChatCtx.Provider value={ctx}>
      <div className="flex h-screen overflow-hidden bg-surface">
        <IconRail pending={pendingCount} />
        {!ADVANCED_PATHS.some((p) => path?.startsWith(p)) && <Sidebar />}
        <div className="flex min-w-0 flex-1">
          <div className="chat-main flex min-w-0 flex-1 flex-col overflow-hidden">
            {modeChip && (
              <div className="flex shrink-0 items-center justify-end border-b border-ink/6 px-4 py-1.5">
                {u.address ? (
                  <button
                    type="button"
                    onClick={u.disconnect}
                    className="mr-3 rounded-lg border border-ink/10 px-2.5 py-1 font-mono text-[11px] text-ink-muted hover:bg-surface-panel"
                  >
                    {u.address.slice(0, 6)}…{u.address.slice(-4)}
                  </button>
                ) : (
                  <button type="button" className="btn-primary mr-3 py-1.5 text-xs" onClick={() => u.connect()}>
                    Connect wallet
                  </button>
                )}
                <span className="rounded bg-ink/5 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-faint">
                  {modeChip}
                </span>
              </div>
            )}
            <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
          </div>
          {showRightPanel && (
            <aside className="hidden w-72 shrink-0 overflow-y-auto border-l border-ink/8 bg-surface-panel lg:block">
              <AgentPanel agent={selectedAgent} />
              <PortfolioPanel recs={recs} pendingCount={pendingCount} />
            </aside>
          )}
        </div>
      </div>
    </ChatCtx.Provider>
  );
}
