"""Run a single orchestrator tick against live Polymarket data, then exit.

Used by `make verify` and by CI as a smoke test.
"""
from __future__ import annotations

import asyncio

from honeybee.orchestrator import Orchestrator, _setup_logging


async def main() -> None:
    _setup_logging()
    o = Orchestrator()
    await o.ledger.init()
    o._banner()
    await o.tick()


if __name__ == "__main__":
    asyncio.run(main())
