// Money / number / time formatting helpers. Round everything; thousands separators.

export function money(n: number | undefined | null, opts: { sign?: boolean } = {}): string {
  const v = Math.round((n ?? 0) * 100) / 100;
  const abs = Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const sign = opts.sign && v > 0 ? "+" : v < 0 ? "-" : "";
  return `${sign}$${abs}`;
}

export function money0(n: number | undefined | null): string {
  return `$${Math.round(n ?? 0).toLocaleString("en-US")}`;
}

export function micro(n: number | undefined | null): string {
  const v = n ?? 0;
  if (v === 0) return "$0";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

export function cents(price: number): string {
  return `${Math.round(price * 100)}¢`;
}

export function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

export function pnlClass(n: number | undefined | null): string {
  const v = n ?? 0;
  return v > 0 ? "pos" : v < 0 ? "neg" : "zero";
}

export function signed(n: number, digits = 2): string {
  const s = n > 0 ? "+" : "";
  return `${s}${n.toFixed(digits)}`;
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const m = Math.round(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

export function expiryLabel(iso: string | null): string {
  if (!iso) return "no expiry";
  const days = Math.round((new Date(iso).getTime() - Date.now()) / 86400000);
  if (days < 0) return "expired";
  if (days === 0) return "expires today";
  if (days === 1) return "1 day left";
  return `${days} days left`;
}

export function shortWallet(w: string): string {
  if (!w) return "";
  return w.length > 12 ? `${w.slice(0, 6)}…${w.slice(-4)}` : w;
}
