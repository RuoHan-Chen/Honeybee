"""Convenience entrypoint: `python -m honeybee.orchestrator` also works."""
from __future__ import annotations

import asyncio

from honeybee.orchestrator import main

if __name__ == "__main__":
    asyncio.run(main())
