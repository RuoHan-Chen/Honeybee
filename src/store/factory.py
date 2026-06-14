"""Repository factory — selects the storage backend from REPO_BACKEND.

Everything else in the codebase depends only on the abstract Repository, so
swapping SQLite ↔ Supabase is a one-line env change:

    REPO_BACKEND=sqlite     (default — the placeholder)
    REPO_BACKEND=supabase   (real Postgres via Supabase PostgREST)
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .repository import Repository

# Ensure env is available regardless of which entrypoint builds the repo.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def build_repository() -> Repository:
    backend = os.getenv("REPO_BACKEND", "sqlite").strip().lower()
    if backend == "supabase":
        from .supabase_repo import SupabaseRepository
        return SupabaseRepository()
    from .sqlite_repo import SqliteRepository
    return SqliteRepository()
