import Link from 'next/link';

export function AdvancedLayout({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-6 px-6 py-6">
      <div>
        <Link href="/" className="text-xs text-ink-faint hover:text-agent">
          ← Back to chat
        </Link>
        <h1 className="mt-3 font-display text-2xl font-medium text-ink">{title}</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">{description}</p>
      </div>
      {children}
    </div>
  );
}
