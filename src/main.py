"""Entrypoint — python -m src.main [--live]

Default: paper trading (no real funds).
Pass --live to activate LiveWallet (requires POLYMARKET_PRIVATE_KEY in .env).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
for _k in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL"):
    if not os.getenv(_k, "").strip():
        os.environ.pop(_k, None)


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Honeybee autonomous prediction market agent")
    p.add_argument("--live", action="store_true",
                   help="Enable real order submission (requires POLYMARKET_PRIVATE_KEY)")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


def main() -> None:
    from ._console import force_utf8
    force_utf8()
    args = _parse()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    if args.live:
        import os
        if not os.getenv("POLYMARKET_PRIVATE_KEY"):
            print("ERROR: --live requires POLYMARKET_PRIVATE_KEY set in .env", file=sys.stderr)
            sys.exit(1)
        print("WARNING: LIVE MODE — real funds may be used. Ctrl+C to abort.")
        input("Press Enter to confirm or Ctrl+C to cancel: ")

    from .orchestrator import Orchestrator
    asyncio.run(Orchestrator(live=args.live).run())


if __name__ == "__main__":
    main()
