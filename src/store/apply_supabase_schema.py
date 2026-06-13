"""Apply config/supabase_schema.sql to the Supabase Postgres DB via asyncpg.

Reads connection details from .env (SUPABASE_DB_*). Run once:
    python -m src.store.apply_supabase_schema
"""
from __future__ import annotations

import asyncio
import os
import ssl
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")
_SCHEMA = _ROOT / "config" / "supabase_schema.sql"


async def main() -> None:
    sql = _SCHEMA.read_text(encoding="utf-8")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Supabase requires SSL; skip CA verify for simplicity

    conn = await asyncpg.connect(
        host=os.getenv("SUPABASE_DB_HOST"),
        port=int(os.getenv("SUPABASE_DB_PORT", "5432")),
        user=os.getenv("SUPABASE_DB_USER", "postgres"),
        password=os.getenv("SUPABASE_DB_PASSWORD"),
        database=os.getenv("SUPABASE_DB_NAME", "postgres"),
        ssl=ctx,
        timeout=30,
    )
    try:
        await conn.execute(sql)  # multi-statement script (no args → simple protocol)
        rows = await conn.fetch(
            "select table_name from information_schema.tables "
            "where table_schema='public' order by table_name"
        )
        print("Schema applied. Public tables:")
        for r in rows:
            print(" -", r["table_name"])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
