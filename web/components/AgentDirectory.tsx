'use client';

import { useEffect, useState } from 'react';
import { api, type Agent, type Reputation } from '@/lib/api';

interface Props {
  agents: Agent[];
  selectedEns: string;
  onSelect: (ens: string) => void;
}

function AgentCard({
  agent,
  selected,
  onSelect,
}: {
  agent: Agent;
  selected: boolean;
  onSelect: () => void;
}) {
  const [rep, setRep] = useState<Reputation | null>(null);

  useEffect(() => {
    api.reputation(agent.ens).then(setRep).catch(() => {});
  }, [agent.ens]);

  return (
    <button
      type="button"
      onClick={onSelect}
      className={
        'card-terminal w-full text-left transition ' +
        (selected ? 'border-agent/40 ring-1 ring-agent/20' : 'hover:border-ink/15')
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold text-ink">{agent.label}</div>
          <div className="font-mono text-xs text-agent">{agent.ens}</div>
        </div>
        <span className="pill text-ink-muted">{agent.venue}</span>
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        {agent.llm_tier} · Kelly {agent.kelly_fraction} · floor {agent.confidence_floor}
      </p>
      {rep && (
        <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
          <div className="rounded-lg bg-ink/5 py-2">
            <div className="font-semibold tabular-nums text-ink">{rep.recommendations}</div>
            <div className="text-[10px] uppercase tracking-wider text-ink-faint">Research</div>
          </div>
          <div className="rounded-lg bg-ink/5 py-2">
            <div className="font-semibold tabular-nums text-ink">{rep.executed_trades}</div>
            <div className="text-[10px] uppercase tracking-wider text-ink-faint">Trades</div>
          </div>
          <div className="rounded-lg bg-ink/5 py-2">
            <div className="font-semibold tabular-nums text-ink">{rep.resolutions_anchored}</div>
            <div className="text-[10px] uppercase tracking-wider text-ink-faint">Resolved</div>
          </div>
        </div>
      )}
    </button>
  );
}

export function AgentDirectory({ agents, selectedEns, onSelect }: Props) {
  const sorted = [...agents].sort((a, b) => {
    if (a.ens === selectedEns) return -1;
    if (b.ens === selectedEns) return 1;
    return a.label.localeCompare(b.label);
  });

  return (
    <div className="space-y-3">
      {sorted.map((a) => (
        <AgentCard
          key={a.ens}
          agent={a}
          selected={selectedEns === a.ens}
          onSelect={() => onSelect(a.ens)}
        />
      ))}
    </div>
  );
}
