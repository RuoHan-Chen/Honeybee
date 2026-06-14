#!/usr/bin/env python3
"""Server-side auto-trader — executes the orchestrator's pending recommendations
as REAL Kalshi (demo) orders, with no browser/wallet/AutoPilot dependency.

Every tick it approves pending recs that fit the limits (per-trade size + daily
cap). Approve → /broker/submit → submitKalshiAsUser → real signed demo order.

Run:  .venv/bin/python scripts/auto_trader.py
Env:  AUTO_TRADER_MAX_PER_TRADE (default 10)  AUTO_TRADER_DAILY_CAP (default 60)
      AUTO_TRADER_TICK_SEC (default 20)        HONEYBEE_API (default :8000)
"""
from __future__ import annotations

import os
import re
import time

import httpx

API = os.getenv("HONEYBEE_API", "http://127.0.0.1:8000")
MAX_PER_TRADE = float(os.getenv("AUTO_TRADER_MAX_PER_TRADE", "10"))
DAILY_CAP = float(os.getenv("AUTO_TRADER_DAILY_CAP", "60"))
TICK = int(os.getenv("AUTO_TRADER_TICK_SEC", "20"))


def main() -> None:
    print(f"auto-trader: API={API} max/trade=${MAX_PER_TRADE} daily_cap=${DAILY_CAP} tick={TICK}s")
    spent = 0.0
    seen: set[str] = set()           # rec_ids already attempted
    traded_series: set[str] = set()  # one trade per event series (avoid strike spam)
    while True:
        try:
            recs = httpx.get(
                f"{API}/recommendations", params={"status": "pending", "limit": 50}, timeout=10
            ).json()
            for r in recs:
                rid = r.get("rec_id")
                if not rid or rid in seen:
                    continue
                size = float(r.get("suggested_size_usd") or 0)
                if size <= 0 or size > MAX_PER_TRADE:
                    continue
                series = re.split(r"-\d", str(r.get("market_id")))[0]  # event-level
                if series in traded_series:
                    continue  # already traded this event — skip its other strikes
                traded_series.add(series)
                if spent + size > DAILY_CAP:
                    print(f"  daily cap ${DAILY_CAP} reached (spent ${spent:.2f}) — standing down")
                    break
                seen.add(rid)
                try:
                    res = httpx.post(
                        f"{API}/recommendations/{rid}/approve",
                        json={"creds": {}}, timeout=60,
                    ).json()
                    fill = res.get("fill", {}) or {}
                    filled = float(fill.get("filled_usd") or 0)
                    spent += filled or size
                    print(f"  ✓ {r.get('venue')} {str(r.get('market_id'))[:26]:26} "
                          f"{r.get('side')} ${filled:.2f} @ {fill.get('avg_price')} "
                          f"order={str(fill.get('broker_ref'))[:13]}  (spent ${spent:.2f})")
                except Exception as e:
                    print(f"  approve failed for {rid[:8]}: {e}")
        except Exception as e:
            print("  tick error:", e)
        time.sleep(TICK)


if __name__ == "__main__":
    main()
