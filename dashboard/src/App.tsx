import { useEffect, useState } from "react";
import { api, type ExposureRow, type Position, type Summary } from "./lib/api";
import { Header } from "./components/Header";
import { KpiRow } from "./components/KpiRow";
import { ExposureBar } from "./components/ExposureBar";
import { PositionCard } from "./components/PositionCard";
import { Calibration } from "./components/Calibration";

type Tab = "open" | "resolved";

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [exposure, setExposure] = useState<ExposureRow[]>([]);
  const [open, setOpen] = useState<Position[]>([]);
  const [resolved, setResolved] = useState<Position[]>([]);
  const [tab, setTab] = useState<Tab>("open");
  const [theme, setTheme] = useState<string>(
    () => localStorage.getItem("hb-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("hb-theme", theme);
  }, [theme]);

  useEffect(() => {
    Promise.all([
      api.summary(),
      api.exposure(),
      api.positions("open"),
      api.positions("resolved"),
    ])
      .then(([s, e, o, r]) => {
        setSummary(s);
        setExposure(e);
        setOpen(o);
        setResolved(r);
      })
      .catch((err) => setError(String(err)));
  }, []);

  if (error) {
    return (
      <div className="app">
        <div className="empty">
          Could not reach the API at <code>/api</code>. Is the FastAPI server running on :8000?
          <br />
          <small>{error}</small>
        </div>
      </div>
    );
  }

  const list = tab === "open" ? open : resolved;

  return (
    <div className="app">
      <Header summary={summary} theme={theme} onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))} />

      <div className="section">
        <KpiRow summary={summary} />
      </div>

      <div className="section">
        <h2 className="section-title">Exposure by category</h2>
        <ExposureBar rows={exposure} />
      </div>

      <div className="section">
        <div className="tabs">
          <button className={`tab ${tab === "open" ? "active" : ""}`} onClick={() => setTab("open")}>
            Open positions ({open.length})
          </button>
          <button className={`tab ${tab === "resolved" ? "active" : ""}`} onClick={() => setTab("resolved")}>
            Resolved ({resolved.length})
          </button>
        </div>

        <div className="pos-list">
          {list.map((p, i) => (
            <PositionCard
              key={p.decision_id}
              pos={p}
              defaultOpen={tab === "open" && i === 0}
              resolved={tab === "resolved"}
            />
          ))}
          {list.length === 0 ? <div className="empty">No {tab} positions</div> : null}
        </div>

        {tab === "resolved" ? <Calibration resolved={resolved} /> : null}
      </div>
    </div>
  );
}
