"""Retention cleanup service for trace sessions and replay artifacts."""

from __future__ import annotations

from typing import Any

from promptetheus.server.artifacts import ArtifactStorage
from promptetheus.server.store import Store


def run_retention_cleanup(
    *,
    store: Store,
    artifact_storage: ArtifactStorage,
    project_id: str | None = None,
    limit: int = 100,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Delete expired sessions after deleting their artifact objects.

    Expiry is selected by the Store so Postgres can use project retention policy
    near the data. Object deletion happens first; sessions with object deletion
    failures are skipped so DB metadata does not disappear while bytes remain.
    """

    limit = max(1, min(limit, 1000))
    expired = store.list_expired_sessions(project_id=project_id, limit=limit)

    session_ids: list[str] = []
    artifacts_seen = 0
    artifacts_deleted = 0
    bytes_deleted = 0
    failures: list[dict[str, str]] = []

    for session in expired:
        session_id = str(session.get("id") or "")
        artifacts = [
            artifact
            for artifact in session.get("artifacts", [])
            if isinstance(artifact, dict)
        ]
        artifacts_seen += len(artifacts)

        if dry_run:
            bytes_deleted += sum(
                int(artifact.get("size_bytes") or 0)
                for artifact in artifacts
                if isinstance(artifact.get("size_bytes"), int)
            )
            session_ids.append(session_id)
            continue

        session_failed = False
        for artifact in artifacts:
            storage_path = str(artifact.get("storage_path") or "")
            if not storage_path:
                continue
            try:
                deleted = artifact_storage.delete(storage_path)
            except Exception as exc:  # keep cleanup best-effort and auditable
                failures.append(
                    {
                        "session_id": session_id,
                        "artifact_id": str(artifact.get("artifact_id") or ""),
                        "storage_path": storage_path,
                        "error": str(exc),
                    }
                )
                session_failed = True
                continue
            if deleted:
                artifacts_deleted += 1
                size_bytes = artifact.get("size_bytes")
                if isinstance(size_bytes, int):
                    bytes_deleted += size_bytes
        if not session_failed:
            session_ids.append(session_id)

    sessions_deleted = 0 if dry_run else store.delete_sessions(session_ids)
    return {
        "dry_run": dry_run,
        "project_id": project_id,
        "limit": limit,
        "scanned_sessions": len(expired),
        "deleted_sessions": sessions_deleted,
        "deleted_artifacts": artifacts_deleted,
        "sessions_matched": len(expired),
        "sessions_deleted": sessions_deleted,
        "artifacts_seen": artifacts_seen,
        "artifacts_deleted": artifacts_deleted,
        "bytes_deleted": bytes_deleted,
        "failures": failures,
    }
