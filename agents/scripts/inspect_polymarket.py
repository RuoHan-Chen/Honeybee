"""Print stats on the first page of Polymarket markets to calibrate filters."""
import asyncio

from honeybee.venues import PolymarketAdapter


async def main():
    p = PolymarketAdapter()
    ms = await p.list_markets()
    print(f"total markets: {len(ms)}")
    with_close = [m for m in ms if m.close_time]
    print(f"with close_time: {len(with_close)}")
    vols = sorted([m.volume_24h for m in ms])
    if vols:
        print(f"vol24h pct: min={vols[0]:.0f}  p25={vols[len(vols)//4]:.0f}  p50={vols[len(vols)//2]:.0f}  p75={vols[3*len(vols)//4]:.0f}  max={vols[-1]:.0f}")
    spreads = sorted([m.spread for m in ms])
    if spreads:
        print(f"spread pct: min={spreads[0]:.3f}  p50={spreads[len(spreads)//2]:.3f}  max={spreads[-1]:.3f}")
    print("\nfirst 5 markets:")
    for m in ms[:5]:
        print(f"  - vol24h=${m.volume_24h:,.0f}  spread={m.spread:.3f}  prices={m.prices}  close={m.close_time}  | {m.question[:80]}")
    await p.close()

asyncio.run(main())
