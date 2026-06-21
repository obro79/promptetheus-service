"""Uvicorn app factory for the optional live-agent E2E test.

This module is imported by a subprocess. It wires the service to the hosted
Supabase Postgres URL and registers the per-run project API key / console token
that the test seeded in Postgres.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server import create_app  # noqa: E402
from promptetheus.server.auth import AuthRegistry  # noqa: E402
from promptetheus.server.db.postgres import SupabasePostgresStore  # noqa: E402


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required for live-agent E2E")
    return value


def _build_app():
    database_url = _required_env("PROMPTETHEUS_LIVE_DATABASE_URL")
    workspace_id = _required_env("PROMPTETHEUS_E2E_WORKSPACE_ID")
    project_id = _required_env("PROMPTETHEUS_E2E_PROJECT_ID")
    api_key = _required_env("PROMPTETHEUS_E2E_API_KEY")
    console_token = _required_env("PROMPTETHEUS_E2E_CONSOLE_TOKEN")

    store = SupabasePostgresStore(database_url)
    auth = AuthRegistry(auth_mode="dev")
    auth.register_project(
        project_id=project_id,
        workspace_id=workspace_id,
        api_key=api_key,
    )
    auth.register_console_token(
        console_token,
        workspace_id,
        user_id="live_e2e_user",
        role="owner",
    )
    return create_app(store=store, auth=auth)


app = _build_app()
