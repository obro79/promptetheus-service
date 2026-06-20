"""In-process persistence for the State-0 FastAPI write gateway.

InMemoryStore is the local-dev / test canonical store. It stands in for
Supabase Postgres behind the same Store protocol, so a SupabaseStore can
drop in later without touching the API layer. All tenant data is keyed by
workspace_id; product rows also carry project_id. trace_event is
append-only and correct timeline order is (session_id, seq) — never the
client timestamp.

This module is part of the locked internal contract. Implementers of the
analysis / fix-agent / regression / app layers depend on these signatures.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol

AppendStatus = Literal["accepted", "duplicate", "conflict"]


class AppendResult:
    """Outcome of appending a single event (see Store.append_event)."""

    __slots__ = ("status", "reason", "event")

    def __init__(
        self,
        status: AppendStatus,
        *,
        reason: str | None = None,
        event: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.reason = reason
        self.event = event

    @property
    def accepted(self) -> bool:
        # A duplicate idempotency_key replay is an idempotent success, not a loss.
        return self.status in ("accepted", "duplicate")


class Store(Protocol):
    """Persistence interface used by every server module."""

    # sessions ---------------------------------------------------------------
    def create_session(self, session: dict[str, Any]) -> dict[str, Any]: ...
    def get_session(self, session_id: str) -> dict[str, Any] | None: ...
    def list_sessions(
        self, *, workspace_id: str, project_id: str | None = None
    ) -> list[dict[str, Any]]: ...
    def update_session(
        self, session_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None: ...
    def delete_sessions(self, session_ids: list[str]) -> int: ...

    # projects / tenancy -----------------------------------------------------
    def list_projects(self, *, workspace_id: str) -> list[dict[str, Any]]: ...
    def get_project(self, project_id: str) -> dict[str, Any] | None: ...
    def update_project(
        self, project_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None: ...
    def lookup_project_by_api_key_hash(self, api_key_hash: str) -> Any | None: ...
    def find_workspace_membership(
        self, *, user_id: str, workspace_id: str | None = None
    ) -> dict[str, Any] | None: ...
    def upsert_workspace_member(self, membership: dict[str, Any]) -> dict[str, Any]: ...

    # events -----------------------------------------------------------------
    def append_event(self, session_id: str, event: dict[str, Any]) -> AppendResult: ...
    def get_events(self, session_id: str) -> list[dict[str, Any]]: ...

    # artifacts --------------------------------------------------------------
    def add_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...
    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None: ...
    def list_expired_sessions(
        self, *, project_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    # analysis ---------------------------------------------------------------
    def set_analysis(
        self, session_id: str, analysis: dict[str, Any]
    ) -> dict[str, Any]: ...
    def get_analysis(self, session_id: str) -> dict[str, Any] | None: ...

    # incidents --------------------------------------------------------------
    def upsert_incident(self, incident: dict[str, Any]) -> dict[str, Any]: ...
    def get_incident(self, incident_id: str) -> dict[str, Any] | None: ...
    def list_incidents(self, *, workspace_id: str) -> list[dict[str, Any]]: ...
    def update_incident(
        self, incident_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    # regression -------------------------------------------------------------
    def add_regression_run(self, run: dict[str, Any]) -> dict[str, Any]: ...
    def list_regression_runs(self, incident_id: str) -> list[dict[str, Any]]: ...

    # audit ------------------------------------------------------------------
    def add_audit(self, entry: dict[str, Any]) -> dict[str, Any]: ...
    def list_audit(self, *, workspace_id: str) -> list[dict[str, Any]]: ...


class InMemoryStore:
    """Thread-safe in-memory Store implementation.

    Notes:
        - append_event enforces append-only semantics, idempotency by
          idempotency_key (replays dedupe to duplicate), and seq
          uniqueness (a reused seq with a different key is a conflict).
        - Reads return deep-ish copies (shallow dict copies) so callers cannot
          mutate stored rows in place.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._event_keys: dict[
            str, dict[str, str]
        ] = {}  # session_id -> {idem_key: ...}
        self._event_seqs: dict[
            str, dict[int, str]
        ] = {}  # session_id -> {seq: idem_key}
        self._artifacts: dict[str, dict[str, Any]] = {}
        self._projects: dict[str, dict[str, Any]] = {}
        self._memberships: dict[tuple[str, str], dict[str, Any]] = {}
        self._analysis: dict[str, dict[str, Any]] = {}
        self._incidents: dict[str, dict[str, Any]] = {}
        self._regression: dict[str, list[dict[str, Any]]] = {}
        self._audit: list[dict[str, Any]] = []
        self._counter = 0
        self._bootstrap_dev_tenant()

    def _bootstrap_dev_tenant(self) -> None:
        now = _iso_now()
        self._projects["proj_dev"] = {
            "id": "proj_dev",
            "workspace_id": "ws_dev",
            "name": "Dev Project",
            "api_key_hash": None,
            "api_key_preview": "pt_dev_..._key",
            "api_key_rotated_at": None,
            "retention_days": 30,
            "created_at": now,
        }
        self._memberships[("user_dev", "ws_dev")] = {
            "user_id": "user_dev",
            "workspace_id": "ws_dev",
            "role": "owner",
            "created_at": now,
        }

    def _next_id(self, prefix: str) -> str:
        with self._lock:
            self._counter += 1
            return f"{prefix}_{self._counter}"

    # sessions ---------------------------------------------------------------
    def create_session(self, session: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            session_id = str(session.get("id") or self._next_id("sess"))
            row = {**session, "id": session_id}
            row.setdefault("status", "running")
            row.setdefault("started_at", _iso_now())
            self._sessions[session_id] = row
            self._events.setdefault(session_id, [])
            self._event_keys.setdefault(session_id, {})
            self._event_seqs.setdefault(session_id, {})
            return dict(row)

    def delete_sessions(self, session_ids: list[str]) -> int:
        deleted = 0
        with self._lock:
            for session_id in session_ids:
                if session_id not in self._sessions:
                    continue
                deleted += 1
                self._sessions.pop(session_id, None)
                self._events.pop(session_id, None)
                self._event_keys.pop(session_id, None)
                self._event_seqs.pop(session_id, None)
                for artifact_id, artifact in list(self._artifacts.items()):
                    if artifact.get("session_id") == session_id:
                        self._artifacts.pop(artifact_id, None)
                self._analysis.pop(session_id, None)
        return deleted

    # projects / tenancy -----------------------------------------------------
    def list_projects(self, *, workspace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                _project_public(row)
                for row in self._projects.values()
                if row.get("workspace_id") == workspace_id
            ]
        rows.sort(key=lambda row: str(row.get("name") or row.get("id")))
        return rows

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._projects.get(project_id)
            return _project_public(row) if row is not None else None

    def update_project(
        self, project_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "api_key_hash",
            "api_key_preview",
            "api_key_rotated_at",
            "retention_days",
        }
        with self._lock:
            row = self._projects.get(project_id)
            if row is None:
                return None
            for key, value in patch.items():
                if key in allowed:
                    row[key] = value
            return _project_public(row)

    def lookup_project_by_api_key_hash(self, api_key_hash: str) -> Any | None:
        with self._lock:
            for row in self._projects.values():
                if row.get("api_key_hash") == api_key_hash:
                    return _InMemoryProjectRecord(
                        project_id=str(row["id"]),
                        workspace_id=str(row["workspace_id"]),
                        api_key_hash=api_key_hash,
                        name=str(row.get("name") or "Project"),
                    )
        return None

    def find_workspace_membership(
        self, *, user_id: str, workspace_id: str | None = None
    ) -> dict[str, Any] | None:
        with self._lock:
            if workspace_id is not None:
                row = self._memberships.get((user_id, workspace_id))
                return dict(row) if row is not None else None
            rows = [
                dict(row)
                for (member_user_id, _workspace_id), row in self._memberships.items()
                if member_user_id == user_id
            ]
        rows.sort(key=lambda row: str(row.get("created_at") or row.get("workspace_id")))
        return rows[0] if rows else None

    def upsert_workspace_member(self, membership: dict[str, Any]) -> dict[str, Any]:
        row = dict(membership)
        row.setdefault("created_at", _iso_now())
        key = (str(row["user_id"]), str(row["workspace_id"]))
        with self._lock:
            self._memberships[key] = row
            return dict(row)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._sessions.get(session_id)
            return dict(row) if row is not None else None

    def list_sessions(
        self, *, workspace_id: str, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows: list[dict[str, Any]] = []
            for row in self._sessions.values():
                if row.get("workspace_id") != workspace_id:
                    continue
                if project_id is not None and row.get("project_id") != project_id:
                    continue
                session_row = dict(row)
                session_id = str(session_row.get("id") or "")
                analysis = self._analysis.get(session_id)
                session_row["labels"] = list((analysis or {}).get("labels") or [])
                rows.append(session_row)
        rows.sort(key=lambda row: str(row.get("started_at") or row.get("id")))
        return rows

    def update_session(
        self, session_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._sessions.get(session_id)
            if row is None:
                return None
            row.update(patch)
            return dict(row)

    # events -----------------------------------------------------------------
    def append_event(self, session_id: str, event: dict[str, Any]) -> AppendResult:
        with self._lock:
            self._events.setdefault(session_id, [])
            keys = self._event_keys.setdefault(session_id, {})
            seqs = self._event_seqs.setdefault(session_id, {})

            idem_key = str(event.get("idempotency_key"))
            seq = event.get("seq")

            if idem_key in keys:
                return AppendResult("duplicate", reason="duplicate idempotency_key")

            if isinstance(seq, int) and seq in seqs and seqs[seq] != idem_key:
                return AppendResult(
                    "conflict",
                    reason=f"seq {seq} already recorded with a different idempotency_key",
                )

            stored = dict(event)
            self._events[session_id].append(stored)
            keys[idem_key] = idem_key
            if isinstance(seq, int):
                seqs[seq] = idem_key
            return AppendResult("accepted", event=dict(stored))

    def get_events(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            events = [dict(event) for event in self._events.get(session_id, [])]
        events.sort(key=lambda event: event.get("seq", 0))
        return events

    # artifacts --------------------------------------------------------------
    def add_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            artifact_id = str(artifact.get("artifact_id") or self._next_id("artifact"))
            row = {**artifact, "artifact_id": artifact_id}
            self._artifacts[artifact_id] = row
            return dict(row)

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._artifacts.get(artifact_id)
            return dict(row) if row is not None else None

    def list_expired_sessions(
        self, *, project_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        expired: list[dict[str, Any]] = []
        with self._lock:
            for session in self._sessions.values():
                session_project_id = session.get("project_id")
                if project_id is not None and session_project_id != project_id:
                    continue
                project = self._projects.get(str(session_project_id or ""))
                if project is None:
                    continue
                retention_days = project.get("retention_days")
                if not isinstance(retention_days, int) or retention_days < 0:
                    continue
                started_at = _parse_dt(session.get("started_at"))
                if started_at is None:
                    continue
                if started_at > now - timedelta(days=retention_days):
                    continue
                artifacts = [
                    dict(artifact)
                    for artifact in self._artifacts.values()
                    if artifact.get("session_id") == session.get("id")
                ]
                expired.append({**dict(session), "artifacts": artifacts})
                if len(expired) >= limit:
                    break
        return expired

    # analysis ---------------------------------------------------------------
    def set_analysis(self, session_id: str, analysis: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            row = dict(analysis)
            self._analysis[session_id] = row
            return dict(row)

    def get_analysis(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._analysis.get(session_id)
            return dict(row) if row is not None else None

    # incidents --------------------------------------------------------------
    def upsert_incident(self, incident: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            incident_id = str(incident.get("id") or self._next_id("incident"))
            existing = self._incidents.get(incident_id, {})
            row = {**existing, **incident, "id": incident_id}
            self._incidents[incident_id] = row
            return dict(row)

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._incidents.get(incident_id)
            return dict(row) if row is not None else None

    def list_incidents(self, *, workspace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(row)
                for row in self._incidents.values()
                if row.get("workspace_id") == workspace_id
            ]
        rows.sort(key=lambda row: str(row.get("id")))
        return rows

    def update_incident(
        self, incident_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._incidents.get(incident_id)
            if row is None:
                return None
            row.update(patch)
            return dict(row)

    # regression -------------------------------------------------------------
    def add_regression_run(self, run: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            run_id = str(run.get("id") or self._next_id("regrun"))
            incident_id = str(run.get("incident_id"))
            row = {**run, "id": run_id}
            self._regression.setdefault(incident_id, []).append(row)
            return dict(row)

    def list_regression_runs(self, incident_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._regression.get(incident_id, [])]

    # audit ------------------------------------------------------------------
    def add_audit(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            row = {**entry, "id": self._next_id("audit")}
            self._audit.append(row)
            return dict(row)

    def list_audit(self, *, workspace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(row)
                for row in self._audit
                if row.get("workspace_id") == workspace_id
            ]


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _project_public(row: dict[str, Any]) -> dict[str, Any]:
    public = dict(row)
    public.pop("api_key_hash", None)
    public.setdefault("api_key_preview", None)
    public.setdefault("retention_days", 30)
    return public


class _InMemoryProjectRecord:
    __slots__ = ("api_key_hash", "name", "project_id", "workspace_id")

    def __init__(
        self, *, project_id: str, workspace_id: str, api_key_hash: str, name: str
    ) -> None:
        self.project_id = project_id
        self.workspace_id = workspace_id
        self.api_key_hash = api_key_hash
        self.name = name
