#!/usr/bin/env python3
"""Verify P2 migration files are present and structurally complete."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO_ROOT / "db" / "migrations"

REQUIRED_FILES = [
    "0001_canonical_entities.sql",
    "0002_rls_policies.sql",
    "0003_dev_seed.sql",
    "0004_auth_tenancy.sql",
    "0005_supabase_storage_artifacts.sql",
]

REQUIRED_TABLES = [
    "workspace",
    "workspace_member",
    "project",
    "agent",
    "trace_session",
    "trace_event",
    "replay_artifact",
    "analysis_result",
    "incident",
    "regression_run",
    "connected_repo",
    "audit_log",
]

REQUIRED_IN_0001 = [
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    "CREATE EXTENSION IF NOT EXISTS vector",
    "trace_event_session_seq",
    "incident_inbox",
    "replay_artifact_lookup_idx",
    "analysis_result_workspace_created_idx",
    "regression_run_incident_created_idx",
    "embedding vector(1536)",
]

REQUIRED_IN_0002 = [
    "ENABLE ROW LEVEL SECURITY",
    "auth_workspace_id",
    "DROP POLICY IF EXISTS",
    "CREATE POLICY",
]

REQUIRED_IN_0004 = [
    "workspace_member",
    "api_key_preview",
    "api_key_rotated_at",
    "retention_days",
    "auth_user_id",
    "is_workspace_member",
    "is_workspace_owner",
    "workspace_role",
]

REQUIRED_IN_0005 = [
    "storage.buckets",
    "storage.objects",
    "artifacts",
    "allowed_mime_types",
    "video/webm",
    "image/png",
    "image/jpeg",
]


def main() -> int:
    errors: list[str] = []

    for name in REQUIRED_FILES:
        if not (MIGRATIONS / name).is_file():
            errors.append(f"missing migration: {name}")

    migration_text = "\n".join(
        (MIGRATIONS / name).read_text(encoding="utf-8") for name in REQUIRED_FILES
    )
    entities = (MIGRATIONS / "0001_canonical_entities.sql").read_text(encoding="utf-8")
    for table in REQUIRED_TABLES:
        if (
            f"CREATE TABLE {table}" not in migration_text
            and f"CREATE TABLE IF NOT EXISTS {table}" not in migration_text
        ):
            errors.append(f"migrations missing table: {table}")
    for fragment in REQUIRED_IN_0001:
        if fragment not in entities:
            errors.append(f"0001 missing fragment: {fragment}")

    rls = (MIGRATIONS / "0002_rls_policies.sql").read_text(encoding="utf-8")
    for fragment in REQUIRED_IN_0002:
        if fragment not in rls:
            errors.append(f"0002 missing fragment: {fragment}")
    for table in REQUIRED_TABLES:
        if table == "workspace_member":
            continue
        if f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" not in rls:
            errors.append(f"0002 missing RLS enable for: {table}")

    auth = (MIGRATIONS / "0004_auth_tenancy.sql").read_text(encoding="utf-8")
    for fragment in REQUIRED_IN_0004:
        if fragment not in auth:
            errors.append(f"0004 missing fragment: {fragment}")
    if "ALTER TABLE workspace_member ENABLE ROW LEVEL SECURITY" not in auth:
        errors.append("0004 missing RLS enable for: workspace_member")

    storage = (MIGRATIONS / "0005_supabase_storage_artifacts.sql").read_text(
        encoding="utf-8"
    )
    for fragment in REQUIRED_IN_0005:
        if fragment not in storage:
            errors.append(f"0005 missing fragment: {fragment}")

    names = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
    if names != sorted(REQUIRED_FILES):
        errors.append(f"unexpected migration set: {names}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"migrations ok ({len(REQUIRED_FILES)} files, {len(REQUIRED_TABLES)} tables)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
