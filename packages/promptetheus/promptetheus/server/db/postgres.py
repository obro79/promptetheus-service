"""Postgres-backed Store for hosted Supabase deployments.

Uses a direct ``DATABASE_URL`` connection (service role / pooler). RLS is
bypassed for the server principal; tenant isolation is enforced in the API layer
and via RLS for console JWT reads through Supabase client paths in P3+.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from promptetheus.server.store import AppendResult

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - optional server extra
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]
    Jsonb = None  # type: ignore[assignment,misc]


def _require_psycopg() -> None:
    if psycopg is None:
        raise RuntimeError(
            "SupabasePostgresStore requires psycopg. "
            "Install with: uv sync --extra server"
        )


def _iso_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _jsonb(value: Any) -> Any:
    if Jsonb is None:
        return value
    return Jsonb(value) if value is not None else None


def _next_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe shallow copy of a DB row."""

    public: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            public[key] = _iso_timestamp(value)
        elif isinstance(value, uuid.UUID):
            public[key] = str(value)
        else:
            public[key] = value
    return public


class SupabasePostgresStore:
    """Store implementation backed by Supabase Postgres."""

    def __init__(self, database_url: str) -> None:
        _require_psycopg()
        self._database_url = database_url

    def _connect(self) -> Any:
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def _ensure_workspace_project(
        self, cur: Any, workspace_id: str, project_id: str | None
    ) -> None:
        """Create minimal FK parent rows so Store writes match InMemory ergonomics."""

        cur.execute(
            """
            INSERT INTO workspace (id, name)
            VALUES (%s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (workspace_id, workspace_id),
        )
        if project_id is None:
            return
        cur.execute(
            """
            INSERT INTO project (id, workspace_id, name)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, workspace_id, project_id),
        )

    def _session_row_to_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "workspace_id": row["workspace_id"],
            "project_id": row.get("project_id"),
            "user_goal": row.get("user_goal"),
            "agent": row.get("agent"),
            "environment": row.get("environment"),
            "status": row.get("status"),
            "metadata": row.get("metadata") or {},
            "tags": row.get("tags") or [],
            "started_at": _iso_timestamp(row.get("started_at")),
        }

    def _event_row_to_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        event: dict[str, Any] = {
            "type": row["type"],
            "session_id": row["session_id"],
            "workspace_id": row["workspace_id"],
            "project_id": row.get("project_id"),
            "timestamp": _iso_timestamp(row["timestamp"]),
            "seq": row["seq"],
            "idempotency_key": row["idempotency_key"],
            "payload": row.get("payload") or {},
        }
        if row.get("metadata") is not None:
            event["metadata"] = row["metadata"]
        if row.get("span_id"):
            event["span_id"] = row["span_id"]
        if row.get("parent_id") is not None:
            event["parent_id"] = row["parent_id"]
        return event

    def _project_row_to_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "workspace_id": row["workspace_id"],
            "name": row["name"],
            "api_key_preview": row.get("api_key_preview"),
            "api_key_rotated_at": _iso_timestamp(row["api_key_rotated_at"])
            if row.get("api_key_rotated_at") is not None
            else None,
            "retention_days": row.get("retention_days", 30),
            "created_at": _iso_timestamp(row.get("created_at")),
        }

    # sessions ---------------------------------------------------------------
    def create_session(self, session: dict[str, Any]) -> dict[str, Any]:
        session_id = str(session.get("id") or _next_id("sess"))
        row = {
            "id": session_id,
            "workspace_id": session["workspace_id"],
            "project_id": session.get("project_id"),
            "user_goal": session.get("user_goal"),
            "agent": session.get("agent"),
            "environment": session.get("environment"),
            "status": session.get("status") or "running",
            "metadata": session.get("metadata") or {},
            "tags": session.get("tags") or [],
            "started_at": _parse_timestamp(session.get("started_at"))
            if session.get("started_at")
            else datetime.now(timezone.utc),
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._ensure_workspace_project(
                    cur, str(row["workspace_id"]), row.get("project_id")
                )
                cur.execute(
                    """
                    INSERT INTO trace_session (
                      id, workspace_id, project_id, user_goal, agent,
                      environment, status, metadata, tags, started_at
                    ) VALUES (
                      %(id)s, %(workspace_id)s, %(project_id)s, %(user_goal)s,
                      %(agent)s, %(environment)s, %(status)s, %(metadata)s,
                      %(tags)s, %(started_at)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                      workspace_id = EXCLUDED.workspace_id,
                      project_id = EXCLUDED.project_id,
                      user_goal = EXCLUDED.user_goal,
                      agent = EXCLUDED.agent,
                      environment = EXCLUDED.environment,
                      status = EXCLUDED.status,
                      metadata = EXCLUDED.metadata,
                      tags = EXCLUDED.tags,
                      started_at = EXCLUDED.started_at
                    RETURNING *
                    """,
                    {
                        **row,
                        "metadata": _jsonb(row["metadata"]),
                        "tags": _jsonb(row["tags"]),
                    },
                )
                saved = cur.fetchone()
            conn.commit()
        return self._session_row_to_dict(saved or row)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM trace_session WHERE id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._session_row_to_dict(row)

    def list_sessions(
        self, *, workspace_id: str, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        query = """
            SELECT ts.*, COALESCE(ar.labels, '{}') AS analysis_labels
            FROM trace_session ts
            LEFT JOIN analysis_result ar ON ar.session_id = ts.id
            WHERE ts.workspace_id = %s
        """
        params: list[Any] = [workspace_id]
        if project_id is not None:
            query += " AND ts.project_id = %s"
            params.append(project_id)
        query += " ORDER BY ts.started_at, ts.id"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            session_row = self._session_row_to_dict(row)
            labels = row.get("analysis_labels") or []
            session_row["labels"] = list(labels)
            results.append(session_row)
        return results

    def update_session(
        self, session_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "user_goal",
            "agent",
            "environment",
            "status",
            "metadata",
            "tags",
            "project_id",
        }
        updates = {key: value for key, value in patch.items() if key in allowed}
        if not updates:
            return self.get_session(session_id)
        set_clause = ", ".join(f"{key} = %({key})s" for key in updates)
        params = dict(updates)
        if "metadata" in params:
            params["metadata"] = _jsonb(params["metadata"])
        if "tags" in params:
            params["tags"] = _jsonb(params["tags"])
        params["id"] = session_id
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE trace_session SET {set_clause} WHERE id = %(id)s RETURNING *",
                    params,
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            return None
        return self._session_row_to_dict(row)

    def delete_sessions(self, session_ids: list[str]) -> int:
        if not session_ids:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM trace_session WHERE id = ANY(%s) RETURNING id",
                    (session_ids,),
                )
                deleted = cur.fetchall()
            conn.commit()
        return len(deleted)

    # projects / tenancy -----------------------------------------------------
    def list_projects(self, *, workspace_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, workspace_id, name, api_key_preview,
                           api_key_rotated_at, retention_days, created_at
                    FROM project
                    WHERE workspace_id = %s
                    ORDER BY name, id
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall()
        return [self._project_row_to_dict(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, workspace_id, name, api_key_preview,
                           api_key_rotated_at, retention_days, created_at
                    FROM project
                    WHERE id = %s
                    """,
                    (project_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._project_row_to_dict(row)

    def lookup_project_by_api_key_hash(self, api_key_hash: str) -> Any | None:
        with self._connect() as conn:
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
        return type(
            "ProjectRecord",
            (),
            {
                "project_id": row["id"],
                "workspace_id": row["workspace_id"],
                "api_key_hash": row["api_key_hash"],
                "name": row.get("name") or "Project",
            },
        )()

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
        updates = {key: value for key, value in patch.items() if key in allowed}
        if not updates:
            return self.get_project(project_id)
        set_clause = ", ".join(f"{key} = %({key})s" for key in updates)
        params: dict[str, Any] = dict(updates)
        params["id"] = project_id
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE project
                    SET {set_clause}
                    WHERE id = %(id)s
                    RETURNING id, workspace_id, name, api_key_preview,
                              api_key_rotated_at, retention_days, created_at
                    """,
                    params,
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            return None
        return self._project_row_to_dict(row)

    def find_workspace_membership(
        self, *, user_id: str, workspace_id: str | None = None
    ) -> dict[str, Any] | None:
        query = """
            SELECT wm.workspace_id, wm.user_id::text AS user_id, wm.role,
                   wm.created_at, w.name AS workspace_name
            FROM workspace_member wm
            JOIN workspace w ON w.id = wm.workspace_id
            WHERE wm.user_id = %s::uuid
        """
        params: list[Any] = [user_id]
        if workspace_id is not None:
            query += " AND wm.workspace_id = %s"
            params.append(workspace_id)
        query += " ORDER BY wm.created_at, wm.workspace_id LIMIT 1"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
        if row is None:
            return None
        return _public_row(row)

    def upsert_workspace_member(self, membership: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workspace_member (workspace_id, user_id, role)
                    VALUES (%(workspace_id)s, %(user_id)s::uuid, %(role)s)
                    ON CONFLICT (workspace_id, user_id) DO UPDATE SET
                      role = EXCLUDED.role
                    RETURNING workspace_id, user_id::text AS user_id, role, created_at
                    """,
                    membership,
                )
                row = cur.fetchone()
            conn.commit()
        return _public_row(row)

    # events -----------------------------------------------------------------
    def append_event(self, session_id: str, event: dict[str, Any]) -> AppendResult:
        idem_key = str(event.get("idempotency_key"))
        seq = event.get("seq")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT idempotency_key, seq FROM trace_event
                    WHERE session_id = %s
                      AND (idempotency_key = %s OR seq = %s)
                    """,
                    (session_id, idem_key, seq),
                )
                existing = cur.fetchall()
                if existing:
                    for row in existing:
                        if row["idempotency_key"] == idem_key:
                            return AppendResult(
                                "duplicate", reason="duplicate idempotency_key"
                            )
                        if isinstance(seq, int) and row["seq"] == seq:
                            return AppendResult(
                                "conflict",
                                reason=(
                                    f"seq {seq} already recorded with a different "
                                    "idempotency_key"
                                ),
                            )
                cur.execute(
                    "SELECT workspace_id, project_id FROM trace_session WHERE id = %s",
                    (session_id,),
                )
                session = cur.fetchone()
                if session is None:
                    return AppendResult("conflict", reason="unknown session")
                cur.execute(
                    """
                    INSERT INTO trace_event (
                      workspace_id, project_id, session_id, seq, idempotency_key,
                      type, timestamp, span_id, parent_id, payload, metadata
                    ) VALUES (
                      %(workspace_id)s, %(project_id)s, %(session_id)s, %(seq)s,
                      %(idempotency_key)s, %(type)s, %(timestamp)s, %(span_id)s,
                      %(parent_id)s, %(payload)s, %(metadata)s
                    )
                    """,
                    {
                        "workspace_id": session["workspace_id"],
                        "project_id": session.get("project_id"),
                        "session_id": session_id,
                        "seq": seq,
                        "idempotency_key": idem_key,
                        "type": event.get("type"),
                        "timestamp": _parse_timestamp(event.get("timestamp")),
                        "span_id": event.get("span_id"),
                        "parent_id": event.get("parent_id"),
                        "payload": _jsonb(event.get("payload") or {}),
                        "metadata": _jsonb(event.get("metadata")),
                    },
                )
            conn.commit()
        return AppendResult("accepted", event=dict(event))

    def get_events(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM trace_event
                    WHERE session_id = %s
                    ORDER BY seq
                    """,
                    (session_id,),
                )
                rows = cur.fetchall()
        return [self._event_row_to_dict(row) for row in rows]

    # artifacts --------------------------------------------------------------
    def add_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        artifact_id = str(artifact.get("artifact_id") or _next_id("artifact"))
        session = self.get_session(str(artifact["session_id"]))
        workspace_id = str(
            artifact.get("workspace_id") or (session or {}).get("workspace_id") or ""
        )
        project_id = artifact.get("project_id", (session or {}).get("project_id"))
        storage_path = str(artifact.get("storage_path") or "")
        row = {
            "artifact_id": artifact_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "session_id": artifact["session_id"],
            "storage_path": storage_path,
            "content_type": artifact.get("content_type"),
            "size_bytes": artifact.get("size_bytes"),
            "event_time_map": artifact.get("event_time_map") or {},
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO replay_artifact (
                      artifact_id, workspace_id, project_id, session_id, storage_path,
                      content_type, size_bytes, event_time_map
                    ) VALUES (
                      %(artifact_id)s, %(workspace_id)s, %(project_id)s,
                      %(session_id)s, %(storage_path)s, %(content_type)s,
                      %(size_bytes)s, %(event_time_map)s
                    )
                    ON CONFLICT (artifact_id) DO UPDATE SET
                      workspace_id = EXCLUDED.workspace_id,
                      project_id = EXCLUDED.project_id,
                      session_id = EXCLUDED.session_id,
                      storage_path = EXCLUDED.storage_path,
                      content_type = EXCLUDED.content_type,
                      size_bytes = EXCLUDED.size_bytes,
                      event_time_map = EXCLUDED.event_time_map
                    """,
                    {**row, "event_time_map": _jsonb(row["event_time_map"])},
                )
            conn.commit()
        result = {**artifact, "artifact_id": artifact_id, "workspace_id": workspace_id}
        if project_id is not None:
            result["project_id"] = project_id
        if storage_path:
            result["storage_path"] = storage_path
        return result

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM replay_artifact WHERE artifact_id = %s",
                    (artifact_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        public = _public_row(row)
        public.pop("created_at", None)
        return public

    def list_expired_sessions(
        self, *, project_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        query = """
            SELECT ts.*
            FROM trace_session ts
            JOIN project p ON p.id = ts.project_id
            WHERE p.retention_days >= 0
              AND ts.started_at < now() - (p.retention_days * interval '1 day')
        """
        params: list[Any] = []
        if project_id is not None:
            query += " AND ts.project_id = %s"
            params.append(project_id)
        query += " ORDER BY ts.started_at, ts.id LIMIT %s"
        params.append(limit)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                sessions = cur.fetchall()
                session_ids = [row["id"] for row in sessions]
                artifacts_by_session: dict[str, list[dict[str, Any]]] = {
                    str(session_id): [] for session_id in session_ids
                }
                if session_ids:
                    cur.execute(
                        """
                        SELECT * FROM replay_artifact
                        WHERE session_id = ANY(%s)
                        ORDER BY created_at, artifact_id
                        """,
                        (session_ids,),
                    )
                    for artifact in cur.fetchall():
                        public = _public_row(artifact)
                        artifacts_by_session.setdefault(
                            str(artifact["session_id"]), []
                        ).append(public)
        return [
            {
                **self._session_row_to_dict(session),
                "artifacts": artifacts_by_session.get(str(session["id"]), []),
            }
            for session in sessions
        ]

    # analysis ---------------------------------------------------------------
    def set_analysis(
        self, session_id: str, analysis: dict[str, Any]
    ) -> dict[str, Any]:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"unknown session: {session_id}")
        row = dict(analysis)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analysis_result (
                      session_id, workspace_id, project_id, labels, critical_step_seq,
                      confidence, root_cause, detections, fallback
                    ) VALUES (
                      %(session_id)s, %(workspace_id)s, %(project_id)s,
                      %(labels)s, %(critical_step_seq)s, %(confidence)s,
                      %(root_cause)s, %(detections)s, %(fallback)s
                    )
                    ON CONFLICT (session_id) DO UPDATE SET
                      project_id = EXCLUDED.project_id,
                      labels = EXCLUDED.labels,
                      critical_step_seq = EXCLUDED.critical_step_seq,
                      confidence = EXCLUDED.confidence,
                      root_cause = EXCLUDED.root_cause,
                      detections = EXCLUDED.detections,
                      fallback = EXCLUDED.fallback
                    """,
                    {
                        "session_id": session_id,
                        "workspace_id": session["workspace_id"],
                        "project_id": session.get("project_id"),
                        "labels": row.get("labels") or [],
                        "critical_step_seq": row.get("critical_step_seq"),
                        "confidence": row.get("confidence"),
                        "root_cause": row.get("root_cause"),
                        "detections": _jsonb(row.get("detections") or []),
                        "fallback": bool(row.get("fallback", False)),
                    },
                )
            conn.commit()
        return dict(row)

    def get_analysis(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM analysis_result WHERE session_id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return {
            "trace_id": session_id,
            "session_id": session_id,
            "labels": list(row.get("labels") or []),
            "critical_step_seq": row.get("critical_step_seq"),
            "confidence": row.get("confidence"),
            "root_cause": row.get("root_cause"),
            "detections": row.get("detections") or [],
            "fallback": row.get("fallback", False),
        }

    # incidents --------------------------------------------------------------
    def upsert_incident(self, incident: dict[str, Any]) -> dict[str, Any]:
        incident_id = str(incident.get("id") or _next_id("incident"))
        existing = self.get_incident(incident_id) or {}
        row = {**existing, **incident, "id": incident_id}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO incident (
                      id, workspace_id, project_id, label, severity, status,
                      representative_session_id, owner_id, session_ids,
                      critical_step_seq, confidence, pr_url, fix_agent_result
                    ) VALUES (
                      %(id)s, %(workspace_id)s, %(project_id)s, %(label)s,
                      %(severity)s, %(status)s, %(representative_session_id)s,
                      %(owner_id)s, %(session_ids)s, %(critical_step_seq)s,
                      %(confidence)s, %(pr_url)s, %(fix_agent_result)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                      workspace_id = EXCLUDED.workspace_id,
                      project_id = EXCLUDED.project_id,
                      label = EXCLUDED.label,
                      severity = EXCLUDED.severity,
                      status = EXCLUDED.status,
                      representative_session_id = EXCLUDED.representative_session_id,
                      owner_id = EXCLUDED.owner_id,
                      session_ids = EXCLUDED.session_ids,
                      critical_step_seq = EXCLUDED.critical_step_seq,
                      confidence = EXCLUDED.confidence,
                      pr_url = EXCLUDED.pr_url,
                      fix_agent_result = EXCLUDED.fix_agent_result
                    """,
                    {
                        "id": incident_id,
                        "workspace_id": row["workspace_id"],
                        "project_id": row.get("project_id"),
                        "label": row["label"],
                        "severity": row.get("severity"),
                        "status": row.get("status"),
                        "representative_session_id": row.get(
                            "representative_session_id"
                        ),
                        "owner_id": row.get("owner_id"),
                        "session_ids": row.get("session_ids") or [],
                        "critical_step_seq": row.get("critical_step_seq"),
                        "confidence": row.get("confidence"),
                        "pr_url": row.get("pr_url"),
                        "fix_agent_result": _jsonb(row.get("fix_agent_result")),
                    },
                )
            conn.commit()
        return dict(row)

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM incident WHERE id = %s", (incident_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "workspace_id": row["workspace_id"],
            "project_id": row.get("project_id"),
            "label": row["label"],
            "severity": row.get("severity"),
            "status": row.get("status"),
            "representative_session_id": row.get("representative_session_id"),
            "owner_id": row.get("owner_id"),
            "session_ids": list(row.get("session_ids") or []),
            "critical_step_seq": row.get("critical_step_seq"),
            "confidence": row.get("confidence"),
            "pr_url": row.get("pr_url"),
            "fix_agent_result": row.get("fix_agent_result"),
            "created_at": _iso_timestamp(row.get("created_at")),
        }

    def list_incidents(self, *, workspace_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM incident
                    WHERE workspace_id = %s
                    ORDER BY id
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall()
        return [
            {
                "id": row["id"],
                "workspace_id": row["workspace_id"],
                "project_id": row.get("project_id"),
                "label": row["label"],
                "severity": row.get("severity"),
                "status": row.get("status"),
                "representative_session_id": row.get("representative_session_id"),
                "session_ids": list(row.get("session_ids") or []),
                "critical_step_seq": row.get("critical_step_seq"),
                "confidence": row.get("confidence"),
                "pr_url": row.get("pr_url"),
                "fix_agent_result": row.get("fix_agent_result"),
            }
            for row in rows
        ]

    def update_incident(
        self, incident_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        existing = self.get_incident(incident_id)
        if existing is None:
            return None
        return self.upsert_incident({**existing, **patch, "id": incident_id})

    # regression -------------------------------------------------------------
    def add_regression_run(self, run: dict[str, Any]) -> dict[str, Any]:
        run_id = str(run.get("id") or _next_id("regrun"))
        row = {**run, "id": run_id}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO regression_run (
                      id, workspace_id, project_id, incident_id, pr_url,
                      before_pass, before_fail, after_pass, after_fail,
                      user_confirm_count, raw_results_json, fallback
                    ) VALUES (
                      %(id)s, %(workspace_id)s, %(project_id)s, %(incident_id)s,
                      %(pr_url)s, %(before_pass)s, %(before_fail)s,
                      %(after_pass)s, %(after_fail)s, %(user_confirm_count)s,
                      %(raw_results_json)s, %(fallback)s
                    )
                    """,
                    {
                        "id": run_id,
                        "workspace_id": row["workspace_id"],
                        "project_id": row.get("project_id"),
                        "incident_id": row["incident_id"],
                        "pr_url": row.get("pr_url"),
                        "before_pass": row.get("before_pass"),
                        "before_fail": row.get("before_fail"),
                        "after_pass": row.get("after_pass"),
                        "after_fail": row.get("after_fail"),
                        "user_confirm_count": row.get("user_confirm_count", 0),
                        "raw_results_json": _jsonb(row.get("raw_results_json")),
                        "fallback": bool(row.get("fallback", False)),
                    },
                )
            conn.commit()
        return dict(row)

    def list_regression_runs(self, incident_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM regression_run
                    WHERE incident_id = %s
                    ORDER BY created_at, id
                    """,
                    (incident_id,),
                )
                rows = cur.fetchall()
        return [_public_row(row) for row in rows]

    # audit ------------------------------------------------------------------
    def add_audit(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (
                      workspace_id, project_id, action, incident_id,
                      actor_kind, metadata
                    ) VALUES (
                      %(workspace_id)s, %(project_id)s, %(action)s,
                      %(incident_id)s, %(actor_kind)s, %(metadata)s
                    )
                    RETURNING id
                    """,
                    {
                        "workspace_id": entry["workspace_id"],
                        "project_id": entry.get("project_id"),
                        "action": entry["action"],
                        "incident_id": entry.get("incident_id"),
                        "actor_kind": entry.get("actor_kind"),
                        "metadata": _jsonb(entry.get("metadata") or {}),
                    },
                )
                audit_id = cur.fetchone()["id"]
            conn.commit()
        return {**entry, "id": str(audit_id)}

    def list_audit(self, *, workspace_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM audit_log
                    WHERE workspace_id = %s
                    ORDER BY created_at, id
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall()
        return [{**_public_row(row), "id": str(row["id"])} for row in rows]


__all__ = ["SupabasePostgresStore"]
