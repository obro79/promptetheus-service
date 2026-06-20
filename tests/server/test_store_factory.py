"""Factory and env selection for Store backends."""

from __future__ import annotations

import pytest

from promptetheus.server.db.factory import store_from_env
from promptetheus.server.store import InMemoryStore


def test_store_from_env_defaults_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROMPTETHEUS_STORE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    store = store_from_env()
    assert isinstance(store, InMemoryStore)


def test_store_from_env_explicit_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROMPTETHEUS_STORE", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    store = store_from_env()
    assert isinstance(store, InMemoryStore)


def test_store_from_env_postgres_requires_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROMPTETHEUS_STORE", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        store_from_env()


def test_store_from_env_database_url_selects_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("psycopg")
    monkeypatch.delenv("PROMPTETHEUS_STORE", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:pass@localhost:5432/test"
    )
    from promptetheus.server.db.postgres import SupabasePostgresStore

    store = store_from_env()
    assert isinstance(store, SupabasePostgresStore)
