'use client';

import { useEffect, useState } from 'react';
import { api, type Agent, type Reputation } from '@/lib/api';

interface Props {
  agent: Agent | null;
}

export function AgentPanel({ agent }: Props) {
  const [rep, setRep] = useState<Reputation | null>(null);

  useEffect(() => {
    if (!agent) {
      setRep(null);
      return;
    }
    api.reputation(agent.ens).then(setRep).catch(() => setRep(null));
  }, [agent?.ens]);

  if (!agent) {
    return (
      <section className="p-4">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Your agent</h2>
        <p className="mt-3 text-sm text-ink-muted">Select an agent from the sidebar to assign research.</p>
      </section>
    );
  }

  return (
    <section className="p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Your agent</h2>

      <div className="mt-3 rounded-xl border border-agent/20 bg-agent/5 p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-agent text-sm font-semibold text-white">
            {agent.label.slice(0, 1)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-ink">{agent.label}</p>
            <p className="truncate font-mono text-[11px] text-agent">{agent.ens}</p>
          </div>
          <span className="rounded-full bg-edge-yes/15 px-2 py-0.5 text-[10px] font-medium text-edge-yes">
            Active
          </span>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
          <div>
            <dt className="text-ink-faint">Venue</dt>
            <dd className="font-medium capitalize text-ink">{agent.venue}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Model</dt>
            <dd className="font-medium text-ink">{agent.llm_tier}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Kelly</dt>
            <dd className="font-mono text-ink">{agent.kelly_fraction}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Floor</dt>
            <dd className="font-mono text-ink">{agent.confidence_floor}</dd>
          </div>
        </dl>

        {rep && (
          <div className="mt-4 grid grid-cols-3 gap-2 border-t border-agent/10 pt-3 text-center">
            <div>
              <div className="font-mono text-sm font-semibold tabular-nums text-ink">{rep.recommendations}</div>
              <div className="text-[10px] text-ink-faint">Research</div>
            </div>
            <div>
              <div className="font-mono text-sm font-semibold tabular-nums text-ink">{rep.executed_trades}</div>
              <div className="text-[10px] text-ink-faint">Trades</div>
            </div>
            <div>
              <div className="font-mono text-sm font-semibold tabular-nums text-ink">{rep.resolutions_anchored}</div>
              <div className="text-[10px] text-ink-faint">Resolved</div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
