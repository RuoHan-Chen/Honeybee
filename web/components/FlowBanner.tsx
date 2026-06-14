'use client';

import Link from 'next/link';

interface Props {
  message: string;
  href?: string;
  linkLabel?: string;
}

export function FlowBanner({ message, href, linkLabel }: Props) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gold/20 bg-gold/5 px-4 py-3 text-sm">
      <span className="text-ink-muted">{message}</span>
      {href && linkLabel && (
        <Link href={href} className="font-medium text-gold hover:text-gold-light">
          {linkLabel} →
        </Link>
      )}
    </div>
  );
}
