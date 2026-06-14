'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { useUser } from './UserWallet';
import { FundButton } from './FundButton';

const links = [
  { href: '/', label: 'Home' },
  { href: '/marketplace', label: 'Hire' },
  { href: '/fleet', label: 'Fleet' },
  { href: '/inbox', label: 'Inbox' },
  { href: '/settings', label: 'Settings' },
];

export function Nav() {
  const path = usePathname();
  const u = useUser();
  const [pending, setPending] = useState(0);
  const [modeChip, setModeChip] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    async function load() {
      try {
        const [h, recs] = await Promise.all([
          api.health(),
          api.listRecommendations({
            limit: 50,
            status: 'pending',
            ...(u.address ? { user_address: u.address } : {}),
          }),
        ]);
        if (stop) return;
        setPending(recs.length);
        setModeChip(h.dry_run ? 'Paper' : 'Live');
      } catch {
        if (!stop) setModeChip(null);
      }
    }
    load();
    const t = setInterval(load, 15000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [u.address]);

  return (
    <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-midnight/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
        <Link href="/" className="flex shrink-0 items-center gap-2.5">
          <span className="font-display text-xl font-medium text-gold">Honeybee</span>
          {modeChip && (
            <span className="hidden rounded bg-white/[0.06] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-white/45 sm:inline">
              {modeChip}
            </span>
          )}
        </Link>

        <nav className="flex flex-1 justify-center gap-0.5 text-sm">
          {links.map((l) => {
            const active = path === l.href || (l.href !== '/' && path?.startsWith(l.href));
            const isInbox = l.href === '/inbox';
            return (
              <Link
                key={l.href}
                href={l.href}
                className={
                  'relative rounded-lg px-3 py-2 transition ' +
                  (active ? 'bg-white/[0.08] text-white' : 'text-white/60 hover:bg-white/[0.04] hover:text-white/90')
                }
              >
                {l.label}
                {isInbox && pending > 0 && (
                  <span className="ml-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-gold px-1.5 text-[10px] font-semibold text-midnight">
                    {pending}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        {u.address ? (
          <div className="flex shrink-0 items-center gap-2">
            <FundButton />
            <button
              type="button"
              onClick={u.disconnect}
              title="Disconnect"
              className="rounded-lg border border-white/10 px-3 py-1.5 text-xs hover:bg-white/[0.04]"
            >
              <span className="mr-2 inline-block h-1.5 w-1.5 rounded-full bg-edge-yes" />
              <span className="font-mono">{u.address.slice(0, 6)}…{u.address.slice(-4)}</span>
            </button>
          </div>
        ) : (
          <button type="button" className="btn-primary shrink-0 text-xs" onClick={() => u.connect()}>
            Connect wallet
          </button>
        )}
      </div>
    </header>
  );
}
