import Link from 'next/link';

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-white/[0.06] py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-white/40">
          Agents research markets. You keep custody and approve every trade.
        </p>
        <nav className="flex flex-wrap gap-4 text-xs">
          <span className="text-white/30">Advanced</span>
          <Link href="/fleet" className="text-white/50 hover:text-gold">
            Agent fleet
          </Link>
          <Link href="/deposit" className="text-white/50 hover:text-gold">
            Fund via Blink
          </Link>
        </nav>
      </div>
    </footer>
  );
}
