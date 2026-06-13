'use client';
import { useUser } from '@/components/UserWallet';

export default function Settings() {
  const u = useUser();

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="mt-1 text-sm text-white/60">
          Your wallet, execution mode, and per-agent limits. Persisted in your browser.
        </p>
      </div>

      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-white/60">Connected wallet</h2>
        {u.address ? (
          <div className="flex items-center justify-between">
            <div className="font-mono text-sm">{u.address}</div>
            <button className="btn-ghost" onClick={u.disconnect}>Disconnect</button>
          </div>
        ) : (
          <div className="flex items-center justify-between">
            <div className="text-sm text-white/60">No wallet connected.</div>
            <button className="btn-primary" onClick={() => u.connect()}>Connect</button>
          </div>
        )}
        <p className="text-xs text-white/40">
          Privy embedded + external connect will replace this stub once your <code>PRIVY_APP_ID</code> lands.
        </p>
      </section>

      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-white/60">Execution mode</h2>
        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={() => u.setMode('manual')}
            className={'rounded-xl border p-4 text-left transition ' +
              (u.mode === 'manual' ? 'border-honey-500 bg-honey-500/10' : 'border-white/10 hover:border-white/20')}>
            <div className="font-semibold">Manual approval</div>
            <p className="mt-1 text-xs text-white/60">
              Recommendations queue up. You review each one before any trade is sent.
            </p>
          </button>
          <button
            onClick={() => u.setMode('auto')}
            className={'rounded-xl border p-4 text-left transition ' +
              (u.mode === 'auto' ? 'border-honey-500 bg-honey-500/10' : 'border-white/10 hover:border-white/20')}>
            <div className="font-semibold">Auto-execute</div>
            <p className="mt-1 text-xs text-white/60">
              Trades within your limits fire automatically. Anything over the cap still needs approval.
            </p>
          </button>
        </div>
      </section>

      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-white/60">Limits (USD)</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="label">Per-trade cap</label>
            <input type="number" min={1} className="input" value={u.perTradeLimit}
              onChange={(e) => u.setPerTradeLimit(Number(e.target.value))} />
          </div>
          <div>
            <label className="label">Daily cap</label>
            <input type="number" min={1} className="input" value={u.dailyLimit}
              onChange={(e) => u.setDailyLimit(Number(e.target.value))} />
          </div>
        </div>
        <p className="text-xs text-white/40">
          Enforced client-side (UI), server-side (broker connector), and on-chain (AttestationRegistry guards). Defense in depth.
        </p>
      </section>
    </div>
  );
}
