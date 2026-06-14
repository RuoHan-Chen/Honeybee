'use client';

import { useUser } from '@/components/UserWallet';

export default function SettingsPage() {
  const u = useUser();

  return (
    <div className="mx-auto max-w-2xl space-y-8 px-6 py-6">
      <section>
        <h1 className="font-display text-2xl font-medium text-ink">Settings</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Agents never hold your trading funds. You connect your wallet, approve research, and trades go through your own broker account.
        </p>
      </section>

      <section className="card-terminal space-y-4">
        <h2 className="text-xs font-medium uppercase tracking-widest text-ink-faint">Connected wallet</h2>
        {u.address ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="font-mono text-sm text-ink">{u.address}</span>
            <button type="button" className="btn-ghost text-xs" onClick={u.disconnect}>
              Disconnect
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm text-ink-muted">No wallet connected</span>
            <button type="button" className="btn-primary text-xs" onClick={() => u.connect()}>
              Connect wallet
            </button>
          </div>
        )}
        <p className="text-xs text-ink-faint">
          Privy embedded + external wallets will replace this stub when configured.
        </p>
      </section>

      <section className="card-terminal space-y-4">
        <h2 className="text-xs font-medium uppercase tracking-widest text-ink-faint">Execution mode</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => u.setMode('manual')}
            className={
              'rounded-xl border p-4 text-left transition ' +
              (u.mode === 'manual'
                ? 'border-gold/50 bg-gold/10 ring-1 ring-gold/25'
                : 'border-ink/10 hover:border-ink/20')
            }
          >
            <div className="font-medium text-ink">Manual approval</div>
            <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">
              Every trade waits in your inbox until you approve it.
            </p>
          </button>
          <button
            type="button"
            onClick={() => u.setMode('auto')}
            className={
              'rounded-xl border p-4 text-left transition ' +
              (u.mode === 'auto'
                ? 'border-gold/50 bg-gold/10 ring-1 ring-gold/25'
                : 'border-ink/10 hover:border-ink/20')
            }
          >
            <div className="font-medium text-ink">Auto-execute</div>
            <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">
              Trades within your limits submit automatically. Larger sizes still need approval.
            </p>
          </button>
        </div>
      </section>

      <section className="card-terminal space-y-4">
        <h2 className="text-xs font-medium uppercase tracking-widest text-ink-faint">Trade limits (USD)</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="per-trade">Per trade</label>
            <input
              id="per-trade"
              type="number"
              min={1}
              className="input"
              value={u.perTradeLimit}
              onChange={(e) => u.setPerTradeLimit(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="label" htmlFor="daily">Daily</label>
            <input
              id="daily"
              type="number"
              min={1}
              className="input"
              value={u.dailyLimit}
              onChange={(e) => u.setDailyLimit(Number(e.target.value))}
            />
          </div>
        </div>
        <p className="text-xs text-ink-faint">
          Limits apply in the UI, broker connector, and on-chain attestation guards.
        </p>
      </section>
    </div>
  );
}
