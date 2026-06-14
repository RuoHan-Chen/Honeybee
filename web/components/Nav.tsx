'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useUser } from './UserWallet';

const links = [
  { href: '/', label: 'Dashboard' },
  { href: '/marketplace', label: 'Marketplace' },
  { href: '/fleet', label: 'Agent Fleet' },
  { href: '/deposit', label: 'Fund' },
  { href: '/trades', label: 'Recommendations' },
  { href: '/settings', label: 'Settings' },
];

export function Nav() {
  const path = usePathname();
  const u = useUser();

  return (
    <header className="border-b border-white/10 bg-ink-900/70 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4">
        <Link href="/" className="flex items-center gap-2 text-lg font-semibold">
          <span className="text-2xl">🐝</span>
          <span>Honeybee</span>
          <span className="ml-2 hidden rounded bg-white/5 px-2 py-0.5 text-xs text-white/60 md:inline">
            long-tail research agents on Arc
          </span>
        </Link>

        <nav className="flex flex-1 justify-center gap-1 text-sm">
          {links.map((l) => {
            const active = path === l.href || (l.href !== '/' && path?.startsWith(l.href));
            return (
              <Link key={l.href} href={l.href}
                className={'rounded-lg px-3 py-1.5 transition ' +
                  (active ? 'bg-honey-500 text-ink-900' : 'text-white/70 hover:bg-white/5')}>
                {l.label}
              </Link>
            );
          })}
        </nav>

        {u.address ? (
          <button onClick={u.disconnect} title="Disconnect"
            className="rounded-lg border border-white/10 px-3 py-1.5 text-xs hover:bg-white/5">
            <span className="mr-2 inline-block h-2 w-2 rounded-full bg-emerald-400" />
            <span className="font-mono">{u.address.slice(0, 6)}…{u.address.slice(-4)}</span>
          </button>
        ) : (
          <button className="btn-primary" onClick={() => u.connect()}>Connect wallet</button>
        )}
      </div>
    </header>
  );
}
