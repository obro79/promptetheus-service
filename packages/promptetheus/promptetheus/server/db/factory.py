"""Store factory and hosted DB helpers."""

from __future__ import annotations

import os

from promptetheus.server.store import InMemoryStore, Store

__all__ = ["store_from_env", "resolve_database_url"]


def resolve_database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")


def store_from_env() -> Store:
    """Return the configured Store backend.

    Defaults to InMemoryStore for credential-free local dev/tests.
    Select Postgres when ``PROMPTETHEUS_STORE=postgres`` or when
    ``DATABASE_URL`` / ``SUPABASE_DB_URL`` is set (unless explicitly
    ``PROMPTETHEUS_STORE=memory``).
  """

    kind = os.environ.get("PROMPTETHEUS_STORE", "").strip().lower()
    database_url = resolve_database_url()

    if kind == "memory":
        return InMemoryStore()
    if kind == "postgres" or (kind != "memory" and database_url):
        from promptetheus.server.db.postgres import SupabasePostgresStore

        if not database_url:
            raise RuntimeError(
                "PROMPTETHEUS_STORE=postgres requires DATABASE_URL or SUPABASE_DB_URL"
            )
        return SupabasePostgresStore(database_url)
    return InMemoryStore()
