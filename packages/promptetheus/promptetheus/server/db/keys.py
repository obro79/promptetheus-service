"""Hosted project API-key lookup scaffolding (P2.9 partial; full auth in P3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from promptetheus.server.auth import Project, WorkspaceMembership, hash_api_key


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    workspace_id: str
    api_key_hash: str
    name: str


def lookup_project_by_api_key(store: Any, api_key: str) -> Project | None:
    """Resolve a project API key via Postgres when available.

    Falls back to None when the store has no DB lookup hook (InMemoryStore).
    """

    lookup = getattr(store, "lookup_project_by_api_key_hash", None)
    if not callable(lookup):
        return None
    record = lookup(hash_api_key(api_key))
    if record is None:
        return None
    if isinstance(record, dict):
        return Project(
            project_id=str(record["id"]),
            workspace_id=str(record["workspace_id"]),
            api_key_hash=str(record["api_key_hash"]),
            name=str(record.get("name") or "Project"),
        )
    return Project(
        project_id=record.project_id,
        workspace_id=record.workspace_id,
        api_key_hash=record.api_key_hash,
        name=record.name,
    )


def attach_project_lookup_to_postgres_store(store: Any) -> Any:
    """Bind hosted auth lookup helpers onto a Postgres store instance."""

    if not callable(getattr(store, "_connect", None)):
        return store

    def _lookup(api_key_hash: str) -> ProjectRecord | None:
        with store._connect() as conn:  # noqa: SLF001 — internal wiring
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, workspace_id, api_key_hash, name
                    FROM project
                    WHERE api_key_hash = %s
                    LIMIT 1
                    """,
                    (api_key_hash,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return ProjectRecord(
            project_id=row["id"],
            workspace_id=row["workspace_id"],
            api_key_hash=row["api_key_hash"],
            name=row.get("name") or "Project",
        )

    setattr(store, "lookup_project_by_api_key_hash", _lookup)
    return store


def lookup_workspace_membership(
    store: Any, user_id: str, workspace_id: str | None
) -> WorkspaceMembership | None:
    """Resolve a Supabase Auth user id to a workspace membership."""

    lookup = getattr(store, "find_workspace_membership", None)
    if not callable(lookup):
        return None
    row = lookup(user_id=user_id, workspace_id=workspace_id)
    if row is None:
        return None
    role = row.get("role")
    if role not in ("owner", "member"):
        return None
    return WorkspaceMembership(
        workspace_id=str(row["workspace_id"]),
        user_id=str(row["user_id"]),
        role=role,
    )
