import type { Summary } from "../lib/api";
import { money0, shortWallet } from "../lib/format";

export function Header({
  summary,
  theme,
  onToggleTheme,
}: {
  summary: Summary | null;
  theme: string;
  onToggleTheme: () => void;
}) {
  const ens = summary?.agent.ens || "honeybee.agent.eth";
  const wallet = shortWallet(summary?.agent.wallet || "");
  const status = summary?.status ?? "paused";

  return (
    <header className="header">
      <div className="brand">
        <div className="brand-mark">🐝</div>
        <div>
          <h1>Honeybee</h1>
          <div className="sub">
            {ens}
            {wallet ? ` · ${wallet}` : ""} · settling on Polygon
          </div>
        </div>
      </div>

      <div className="header-right">
        <span className={`pill ${status}`}>
          <span className="dot" />
          {status === "live" ? "Live" : "Paused"}
        </span>
        <div className="bankroll">
          <div className="label">Bankroll</div>
          <div className="value">{money0(summary?.bankroll)}</div>
        </div>
        <button className="theme-toggle" onClick={onToggleTheme} title="Toggle theme">
          {theme === "dark" ? "☀️" : "🌙"}
        </button>
      </div>
    </header>
  );
}
