"""Store contract parity: InMemoryStore always; Postgres when configured."""

from __future__ import annotations

import os

import pytest

from promptetheus.server.store import InMemoryStore
from tests.server.store_contract import (
    assert_workspace_isolation,
    exercise_store_contract,
)


def test_in_memory_store_contract() -> None:
    store = InMemoryStore()
    exercise_store_contract(store)
    assert_workspace_isolation(store, "ws_other")


@pytest.fixture(scope="module")
def postgres_store():
    database_url = os.environ.get("PROMPTETHEUS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PROMPTETHEUS_TEST_DATABASE_URL not set")

    pytest.importorskip("psycopg")
    from pathlib import Path

    from promptetheus.server.db.postgres import SupabasePostgresStore

    migrations = sorted(
        Path(__file__).resolve().parents[2].glob("db/migrations/*.sql")
    )
    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for path in migrations:
                cur.execute(path.read_text(encoding="utf-8"))
        conn.commit()

    store = SupabasePostgresStore(database_url)
    yield store

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE TABLE
                  audit_log, regression_run, incident, analysis_result,
                  replay_artifact, trace_event, trace_session, connected_repo,
                  agent, project, workspace
                RESTART IDENTITY CASCADE
                """
            )
        conn.commit()


def test_postgres_store_contract(postgres_store) -> None:
    exercise_store_contract(postgres_store)
    assert_workspace_isolation(postgres_store, "ws_other")
