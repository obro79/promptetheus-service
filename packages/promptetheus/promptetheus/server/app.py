"""FastAPI write gateway for the State-0 spine: the 14 locked endpoints.

This is the canonical HTTP boundary for all trace-derived state. The SDK posts
traces/events/artifacts here; the console reads sessions/events/analysis/incidents
and triggers analysis, fix-agent, and regression runs through it. Detection, fix
generation, and regression logic live next to the data (under analysis/,
fix_agent/, regression/) and are invoked from these routes — the console
holds none of that logic.

Persistence flows through the Store protocol (InMemoryStore in State 0).
Auth + workspace resolution flows through AuthRegistry. The in-process SSE hub
(StreamHub) fans accepted events out to GET /api/stream subscribers. All
three are constructed by create_app (or injected for tests) and exposed on
app.state as store / auth / hub.

The status-code mapping (401/403/404/400/413/415 and the per-event 422/conflict
rejections) follows the locked API Contract in technical-architecture.md exactly.
"""

from __future__ import annotations

import gzip
import html
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from promptetheus import schema
from promptetheus.server.artifacts import (
    ArtifactStorage,
    artifact_storage_from_env,
    artifact_storage_path,
    safe_artifact_filename,
)
from promptetheus.server.analysis import classifier
from promptetheus.server.analysis.engine import analyze_session, assemble_incidents
from promptetheus.server.auth import (
    AuthContext,
    AuthRegistry,
    DEV_WORKSPACE_ID,
    WorkspaceMembership,
    api_key_preview,
    generate_project_api_key,
    hash_api_key,
)
from promptetheus.server.fix_agent.runner import (
    build_incident_bundle,
    build_incident_context,
    connected_repo_stub,
)
from promptetheus.server.fix_agent.runners import get_runner
from promptetheus.server.fix_agent.orchestrator import run_loop
from promptetheus.server.github import (
    GitHubConfig,
    create_pull_request,
    github_fallback_forced,
    github_pr_enabled,
)
from promptetheus.server.models import INCIDENT_STATUSES
from promptetheus.server.regression.runner import run_regression
from promptetheus.server.retention import run_retention_cleanup
from promptetheus.server.runtime import RuntimeScope, RuntimeStore, runtime_from_env
from promptetheus.server.db import store_from_env
from promptetheus.server.db.keys import (
    attach_project_lookup_to_postgres_store,
    lookup_project_by_api_key,
)
from promptetheus.server.store import InMemoryStore, Store
from promptetheus.server.stream import StreamHub

__all__ = ["create_app"]

logger = logging.getLogger("promptetheus.server.ingest")

# Artifact upload limits (Storage Contract). Overridable via env for tests/ops.
_DEFAULT_MAX_ARTIFACT_BYTES = 50 * 1024 * 1024  # 50 MiB
_ALLOWED_ARTIFACT_CONTENT_TYPES: frozenset[str] = frozenset(
    {"video/webm", "image/png", "image/jpeg"}
)


class _HTTPError(Exception):
    """Internal control-flow exception mapped to a JSON error response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _max_artifact_bytes() -> int:
    raw = os.environ.get("PROMPTETHEUS_MAX_ARTIFACT_BYTES")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _DEFAULT_MAX_ARTIFACT_BYTES


def _cors_origins() -> list[str]:
    raw = os.environ.get("PROMPTETHEUS_CONSOLE_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env_flag(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _self_host_dashboard_enabled(store: Store) -> bool:
    configured = _env_flag("PROMPTETHEUS_SELF_HOST_DASHBOARD")
    if configured is not None:
        return configured
    return isinstance(store, InMemoryStore)


def _dashboard_int(raw: str | None, *, default: int, minimum: int, maximum: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise _HTTPError(400, "limit must be an integer") from exc
    return max(minimum, min(maximum, value))


def _safe_text(value: Any, *, fallback: str = "n/a") -> str:
    if value is None:
        return fallback
    text = str(value)
    return text if text else fallback


def _clip(value: Any, *, length: int = 160) -> str:
    text = _safe_text(value, fallback="")
    if len(text) <= length:
        return text
    return f"{text[: length - 1]}..."


def _self_host_session_summary(
    store: Store, session: dict[str, Any]
) -> dict[str, Any]:
    session_id = str(session.get("id") or "")
    event_count = len(store.get_events(session_id)) if session_id else 0
    return {
        "id": session_id,
        "agent": session.get("agent"),
        "user_goal": session.get("user_goal"),
        "environment": session.get("environment"),
        "status": session.get("status"),
        "started_at": session.get("started_at"),
        "project_id": session.get("project_id"),
        "labels": session.get("labels") or [],
        "tags": session.get("tags") or [],
        "event_count": event_count,
    }


def _self_host_event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": event.get("seq"),
        "type": event.get("type"),
        "timestamp": event.get("timestamp"),
        "idempotency_key": event.get("idempotency_key"),
        "payload": event.get("payload") or {},
    }


def _self_host_snapshot(
    store: Store,
    *,
    workspace_id: str,
    project_id: str | None,
    selected_session_id: str | None,
    limit: int,
) -> dict[str, Any]:
    sessions = store.list_sessions(workspace_id=workspace_id, project_id=project_id)
    sessions_latest = list(reversed(sessions))[:limit]

    selected = next(
        (
            session
            for session in sessions
            if selected_session_id is not None
            and str(session.get("id")) == selected_session_id
        ),
        None,
    )
    if selected is None and sessions_latest:
        selected = sessions_latest[0]

    selected_id = str(selected.get("id")) if selected is not None else None
    events = store.get_events(selected_id) if selected_id else []
    projects = store.list_projects(workspace_id=workspace_id)
    status_counts: dict[str, int] = {}
    agents: set[str] = set()
    for session in sessions:
        status = str(session.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        agent = session.get("agent")
        if agent:
            agents.add(str(agent))

    return {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "session_count": len(sessions),
        "event_count": sum(
            len(store.get_events(str(session.get("id") or ""))) for session in sessions
        ),
        "status_counts": status_counts,
        "agents": sorted(agents),
        "projects": projects,
        "sessions": [
            _self_host_session_summary(store, session) for session in sessions_latest
        ],
        "selected_session": (
            _self_host_session_summary(store, selected)
            if selected is not None
            else None
        ),
        "selected_events": [
            _self_host_event_summary(event) for event in events[-50:]
        ],
    }


def _self_host_dashboard_html(snapshot: dict[str, Any]) -> str:
    def e(value: Any) -> str:
        return html.escape(_safe_text(value), quote=True)

    def href(session_id: str) -> str:
        params = {"workspace_id": str(snapshot["workspace_id"]), "session_id": session_id}
        project_id = snapshot.get("project_id")
        if project_id is not None:
            params["project_id"] = str(project_id)
        return "/self-host?" + html.escape(urlencode(params), quote=True)

    sessions = snapshot["sessions"]
    selected = snapshot["selected_session"]
    events = snapshot["selected_events"]
    status_counts = snapshot["status_counts"]
    agents = snapshot["agents"]

    rows = "\n".join(
        f"""
        <tr>
          <td><a href="{href(str(session["id"]))}">{e(session["id"])}</a></td>
          <td>{e(session.get("agent"))}</td>
          <td>{e(_clip(session.get("user_goal"), length=96))}</td>
          <td><span class="pill">{e(session.get("status"))}</span></td>
          <td>{e(session.get("event_count"))}</td>
          <td>{e(session.get("started_at"))}</td>
        </tr>
        """
        for session in sessions
    )
    if not rows:
        rows = """
        <tr>
          <td colspan="6" class="empty">No trace sessions yet.</td>
        </tr>
        """

    event_rows = "\n".join(
        f"""
        <li>
          <div class="event-top">
            <span>#{e(event.get("seq"))}</span>
            <strong>{e(event.get("type"))}</strong>
            <span>{e(event.get("timestamp"))}</span>
          </div>
          <pre>{e(json.dumps(event.get("payload") or {}, indent=2, default=str))}</pre>
        </li>
        """
        for event in events
    )
    if not event_rows:
        event_rows = '<li class="empty">No events for this session yet.</li>'

    selected_title = (
        f"{e(selected.get('id'))} · {e(selected.get('agent'))}"
        if selected is not None
        else "No session selected"
    )
    status_text = ", ".join(
        f"{name}: {count}" for name, count in sorted(status_counts.items())
    ) or "none"
    agent_text = ", ".join(agents) or "none"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Promptetheus Self-Host</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #050607;
      --panel: #0d1014;
      --panel-2: #11161c;
      --border: #242b35;
      --text: #eef3f8;
      --muted: #8e9aaa;
      --accent: #7dd3fc;
      --ok: #86efac;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 13px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    header, main {{ max-width: 1180px; margin: 0 auto; padding: 20px; }}
    header {{
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 16px;
      justify-content: space-between;
      align-items: center;
    }}
    h1 {{ margin: 0; font-size: 18px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 13px; color: var(--muted); }}
    .nav {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }}
    .stat, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    .stat {{ padding: 12px; }}
    .label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; }}
    .value {{ margin-top: 4px; font-size: 18px; font-weight: 650; }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(320px, .85fr); gap: 14px; margin-top: 14px; }}
    .panel {{ overflow: hidden; }}
    .panel-head {{ padding: 14px 16px; border-bottom: 1px solid var(--border); }}
    .panel-body {{ padding: 14px 16px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: 11px; text-transform: uppercase; background: var(--panel-2); }}
    td {{ color: #d8e0ea; }}
    .pill {{ display: inline-flex; padding: 2px 7px; border: 1px solid var(--border); border-radius: 999px; color: var(--ok); }}
    .events {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }}
    .events li {{ border: 1px solid var(--border); border-radius: 8px; background: var(--panel-2); }}
    .event-top {{ display: flex; gap: 10px; padding: 9px 11px; color: var(--muted); border-bottom: 1px solid var(--border); }}
    pre {{ margin: 0; padding: 11px; overflow: auto; max-height: 220px; color: #d7e4f0; }}
    code {{ color: var(--accent); }}
    .empty {{ color: var(--muted); padding: 16px; }}
    @media (max-width: 820px) {{
      header {{ align-items: flex-start; flex-direction: column; }}
      .stats, .grid {{ grid-template-columns: 1fr; }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Promptetheus Self-Host</h1>
      <div class="label">Minimal FastAPI dashboard for local/self-host smoke tests</div>
    </div>
    <nav class="nav">
      <a href="/health">health</a>
      <a href="/docs">docs</a>
      <a href="/openapi.json">openapi</a>
      <a href="/self-host.json">json</a>
    </nav>
  </header>
  <main>
    <section class="stats">
      <div class="stat"><div class="label">Workspace</div><div class="value">{e(snapshot["workspace_id"])}</div></div>
      <div class="stat"><div class="label">Sessions</div><div class="value">{e(snapshot["session_count"])}</div></div>
      <div class="stat"><div class="label">Events</div><div class="value">{e(snapshot["event_count"])}</div></div>
      <div class="stat"><div class="label">Agents</div><div class="value">{e(len(agents))}</div></div>
    </section>
    <section class="grid">
      <div class="panel">
        <div class="panel-head">
          <h2>Recent sessions</h2>
          <div class="label">Status: {e(status_text)} · Agents: {e(agent_text)}</div>
        </div>
        <table>
          <thead>
            <tr><th>Trace</th><th>Agent</th><th>Goal</th><th>Status</th><th>Events</th><th>Started</th></tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      <aside class="panel">
        <div class="panel-head">
          <h2>Selected trace</h2>
          <div>{selected_title}</div>
        </div>
        <div class="panel-body">
          <div class="label">SDK env</div>
          <pre><code>export PROMPTETHEUS_API_URL=http://127.0.0.1:4318
export PROMPTETHEUS_API_KEY=pt_dev_key
python your_agent.py</code></pre>
        </div>
        <div class="panel-head"><h2>Recent events</h2></div>
        <div class="panel-body">
          <ul class="events">{event_rows}</ul>
        </div>
      </aside>
    </section>
  </main>
</body>
</html>"""


def create_app(
    store: Store | None = None,
    auth: AuthRegistry | None = None,
    artifact_storage: ArtifactStorage | None = None,
    runtime_store: RuntimeStore | None = None,
) -> FastAPI:
    """Construct the Promptetheus FastAPI app.

    Args:
        store: Persistence backend. Defaults to ``store_from_env()`` (InMemoryStore
        locally; Postgres when ``DATABASE_URL`` / ``PROMPTETHEUS_STORE=postgres``).
        auth: Auth/workspace registry. Defaults to a fresh AuthRegistry.
        artifact_storage: Storage backend for artifact bytes. Defaults from env.
        runtime_store: Short-lived agent runtime guidance backend. Defaults from env.

    Returns:
        The configured FastAPI application. app.state.store,
        app.state.auth, and app.state.hub expose the wired components.
    """

    app = FastAPI(title="Promptetheus API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if store is None:
        store = store_from_env()
        attach_project_lookup_to_postgres_store(store)
    app.state.store = store

    def _lookup_membership(
        user_id: str, workspace_id: str | None
    ) -> WorkspaceMembership | None:
        lookup = getattr(store, "find_workspace_membership", None)
        if not callable(lookup):
            return None
        row = lookup(user_id=user_id, workspace_id=workspace_id)
        if not isinstance(row, Mapping):
            return None
        role = row.get("role")
        if role not in ("owner", "member"):
            return None
        resolved_workspace_id = row.get("workspace_id")
        resolved_user_id = row.get("user_id")
        if not isinstance(resolved_workspace_id, str) or not isinstance(
            resolved_user_id, str
        ):
            return None
        return WorkspaceMembership(
            workspace_id=resolved_workspace_id,
            user_id=resolved_user_id,
            role=role,
        )

    app.state.auth = (
        auth
        if auth is not None
        else AuthRegistry(
            project_lookup=lambda api_key: lookup_project_by_api_key(store, api_key),
            membership_lookup=_lookup_membership,
        )
    )
    app.state.artifact_storage = artifact_storage or artifact_storage_from_env()
    app.state.hub = StreamHub()
    app.state.runtime = runtime_store or runtime_from_env()

    # -- helpers ----------------------------------------------------------------

    def _authenticate(request: Request) -> AuthContext:
        requested_workspace_id = request.headers.get(
            "x-promptetheus-workspace-id"
        ) or request.query_params.get("workspace_id")
        ctx = app.state.auth.resolve(
            request.headers.get("authorization"),
            workspace_id=requested_workspace_id,
        )
        if ctx is None:
            raise _HTTPError(401, "missing or invalid credential")
        return ctx

    def _require_principal(ctx: AuthContext, allowed: tuple[str, ...]) -> None:
        if ctx.kind not in allowed:
            raise _HTTPError(403, "principal is not allowed for this endpoint")

    def _require_owner(ctx: AuthContext) -> None:
        if ctx.kind != "console" or ctx.role != "owner":
            raise _HTTPError(403, "workspace owner role is required")

    async def _json_body(request: Request) -> dict[str, Any]:
        if request.headers.get("content-length") in (None, "", "0"):
            return {}
        raw = await request.body()
        if not raw:
            return {}
        # The SDK's durable transport may gzip large batches (Content-Encoding:
        # gzip); Starlette does not auto-decompress request bodies, so decode here.
        encoding = request.headers.get("content-encoding", "").lower()
        if "gzip" in encoding:
            try:
                raw = gzip.decompress(raw)
            except Exception as exc:  # malformed gzip -> 400
                raise _HTTPError(400, "malformed gzip body") from exc
        try:
            body = json.loads(raw)
        except Exception as exc:  # malformed JSON -> 400
            raise _HTTPError(400, "malformed JSON body") from exc
        if not isinstance(body, Mapping):
            raise _HTTPError(400, "request body must be a JSON object")
        return dict(body)

    async def _artifact_body(
        request: Request,
    ) -> tuple[dict[str, Any], bytes | None]:
        content_type = request.headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type in ("", "application/json"):
            return await _json_body(request), None

        raw = await request.body()
        body: dict[str, Any] = {
            "content_type": media_type,
            "size_bytes": len(raw),
            "filename": request.headers.get("x-promptetheus-filename"),
            "artifact_type": request.headers.get("x-promptetheus-artifact-type"),
        }
        artifact_id = request.headers.get("x-promptetheus-artifact-id")
        if artifact_id:
            body["artifact_id"] = artifact_id
        return body, raw

    def _require_session_in_workspace(
        session_id: str, ctx: AuthContext
    ) -> dict[str, Any]:
        session = app.state.store.get_session(session_id)
        if session is None:
            raise _HTTPError(404, "trace not found")
        if session.get("workspace_id") != ctx.workspace_id and not ctx.is_server:
            # Not found vs forbidden: a non-server principal in another workspace
            # must not learn the row exists -> 404 (per the contract's 404 row).
            raise _HTTPError(404, "trace not found")
        return session

    def _require_session_read(session_id: str, ctx: AuthContext) -> dict[str, Any]:
        session = _require_session_in_workspace(session_id, ctx)
        if (
            ctx.kind == "api_key"
            and ctx.project_id is not None
            and session.get("project_id") != ctx.project_id
        ):
            raise _HTTPError(404, "trace not found")
        return session

    def _require_runtime_session(session_id: str, ctx: AuthContext) -> dict[str, Any]:
        session = _require_session_read(session_id, ctx)
        if (
            ctx.project_id is not None
            and session.get("project_id") is not None
            and session.get("project_id") != ctx.project_id
            and not ctx.is_server
        ):
            raise _HTTPError(404, "trace not found")
        return session

    def _runtime_scope(session: dict[str, Any], session_id: str) -> RuntimeScope:
        project_id = session.get("project_id")
        return RuntimeScope(
            workspace_id=str(session.get("workspace_id") or ""),
            project_id=str(project_id) if project_id is not None else None,
            session_id=session_id,
        )

    def _require_incident_in_workspace(
        incident_id: str, ctx: AuthContext
    ) -> dict[str, Any]:
        incident = app.state.store.get_incident(incident_id)
        if incident is None:
            raise _HTTPError(404, "incident not found")
        if incident.get("workspace_id") != ctx.workspace_id and not ctx.is_server:
            raise _HTTPError(404, "incident not found")
        return incident

    def _require_incident_read(incident_id: str, ctx: AuthContext) -> dict[str, Any]:
        incident = _require_incident_in_workspace(incident_id, ctx)
        if (
            ctx.kind == "api_key"
            and ctx.project_id is not None
            and incident.get("project_id") != ctx.project_id
        ):
            raise _HTTPError(404, "incident not found")
        return incident

    def _require_project_in_workspace(project_id: str, ctx: AuthContext) -> dict[str, Any]:
        project = app.state.store.get_project(project_id)
        if project is None or (
            project.get("workspace_id") != ctx.workspace_id and not ctx.is_server
        ):
            raise _HTTPError(404, "project not found")
        return project

    def _optional_text(
        body: dict[str, Any], key: str, default: str, *, max_length: int = 120
    ) -> str:
        value = body.get(key, default)
        if not isinstance(value, str):
            raise _HTTPError(400, f"{key} must be a string")
        text = value.strip()
        if not text:
            raise _HTTPError(400, f"{key} must be a non-empty string")
        if len(text) > max_length:
            raise _HTTPError(400, f"{key} must be {max_length} characters or fewer")
        return text

    def _incident_matches(incident: dict[str, Any], query: str) -> bool:
        # Case-insensitive substring match over the human-meaningful incident
        # fields (label/title/root-cause-ish). Numeric/id fields are excluded so
        # the filter stays a content search rather than an id lookup.
        needle = query.casefold()
        haystacks = [
            incident.get("label"),
            incident.get("title"),
            incident.get("root_cause"),
            incident.get("severity"),
            incident.get("status"),
        ]
        return any(
            needle in str(value).casefold() for value in haystacks if value is not None
        )

    def _events_from_body(body: dict[str, Any]) -> list[Any]:
        if "events" in body:
            events = body.get("events")
            return list(events) if isinstance(events, list) else [events]
        return [body] if body else []

    def _event_ref(index: int, event: Any) -> dict[str, Any]:
        ref: dict[str, Any] = {"index": index}
        if isinstance(event, Mapping) and "idempotency_key" in event:
            ref["idempotency_key"] = event["idempotency_key"]
        return ref

    # -- health -----------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # -- self-host dashboard ---------------------------------------------------

    @app.get("/self-host", response_class=HTMLResponse)
    async def self_host_dashboard(request: Request) -> HTMLResponse:
        if not _self_host_dashboard_enabled(app.state.store):
            raise _HTTPError(404, "self-host dashboard is disabled")
        limit = _dashboard_int(
            request.query_params.get("limit"),
            default=25,
            minimum=1,
            maximum=100,
        )
        snapshot = _self_host_snapshot(
            app.state.store,
            workspace_id=request.query_params.get("workspace_id") or DEV_WORKSPACE_ID,
            project_id=request.query_params.get("project_id"),
            selected_session_id=request.query_params.get("session_id"),
            limit=limit,
        )
        return HTMLResponse(_self_host_dashboard_html(snapshot))

    @app.get("/self-host.json")
    async def self_host_dashboard_data(request: Request) -> dict[str, Any]:
        if not _self_host_dashboard_enabled(app.state.store):
            raise _HTTPError(404, "self-host dashboard is disabled")
        limit = _dashboard_int(
            request.query_params.get("limit"),
            default=25,
            minimum=1,
            maximum=100,
        )
        return _self_host_snapshot(
            app.state.store,
            workspace_id=request.query_params.get("workspace_id") or DEV_WORKSPACE_ID,
            project_id=request.query_params.get("project_id"),
            selected_session_id=request.query_params.get("session_id"),
            limit=limit,
        )

    # -- onboarding ------------------------------------------------------------

    @app.post("/api/onboarding/bootstrap")
    async def bootstrap_onboarding(request: Request) -> JSONResponse:
        user_id = app.state.auth.resolve_console_user_id(
            request.headers.get("authorization")
        )
        if user_id is None:
            raise _HTTPError(401, "missing or invalid console credential")

        body = await _json_body(request)
        workspace_name = _optional_text(
            body, "workspace_name", "Promptetheus Workspace"
        )
        project_name = _optional_text(body, "project_name", "Default Project")
        agent_name = body.get("agent_name")
        if agent_name is not None and not isinstance(agent_name, str):
            raise _HTTPError(400, "agent_name must be a string")
        agent_name = agent_name.strip() if isinstance(agent_name, str) else None
        if agent_name == "":
            raise _HTTPError(400, "agent_name must be a non-empty string")

        raw_key = generate_project_api_key()
        result = app.state.store.ensure_workspace_project_for_user(
            user_id=user_id,
            workspace_name=workspace_name,
            project_name=project_name,
            api_key_hash=hash_api_key(raw_key),
            api_key_preview=api_key_preview(raw_key),
        )
        workspace = result["workspace"]
        project = result["project"]
        if result.get("api_key_created"):
            app.state.auth.replace_project_api_key(
                project_id=str(project["id"]),
                workspace_id=str(project["workspace_id"]),
                api_key=raw_key,
            )
        else:
            raw_key = ""

        agent = None
        if agent_name is not None:
            agent = app.state.store.create_agent(
                {
                    "workspace_id": workspace["id"],
                    "project_id": project["id"],
                    "name": agent_name,
                }
            )

        app.state.store.add_audit(
            {
                "workspace_id": workspace["id"],
                "project_id": project["id"],
                "action": "onboarding_bootstrap",
                "actor_kind": "console",
                "metadata": {
                    "user_id": user_id,
                    "created_workspace": bool(result.get("created_workspace")),
                    "created_project": bool(result.get("created_project")),
                    "api_key_created": bool(result.get("api_key_created")),
                    "agent_id": agent.get("id") if agent else None,
                },
            }
        )

        status_code = (
            201
            if result.get("created_workspace")
            or result.get("created_project")
            or result.get("api_key_created")
            or agent is not None
            else 200
        )
        return JSONResponse(
            {
                "workspace": workspace,
                "membership": result["membership"],
                "project": project,
                "api_key": raw_key or None,
                "api_key_preview": project.get("api_key_preview"),
                "agent": agent,
                "created_workspace": bool(result.get("created_workspace")),
                "created_project": bool(result.get("created_project")),
                "api_key_created": bool(result.get("api_key_created")),
            },
            status_code=status_code,
        )

    # -- ingestion: traces ------------------------------------------------------

    @app.post("/api/traces")
    async def create_trace(request: Request) -> JSONResponse:
        started = time.monotonic()
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        body = await _json_body(request)

        session: dict[str, Any] = {
            "user_goal": body.get("user_goal"),
            "agent": body.get("agent"),
            "environment": body.get("environment"),
            "metadata": body.get("metadata"),
            "tags": body.get("tags"),
            "workspace_id": ctx.workspace_id,
            "project_id": ctx.project_id,
        }
        # Agnostic source tag (browserbase / lambda / ...) threaded through the heal
        # loop so the same pipeline visibly heals incidents from any deployment.
        if body.get("source") is not None:
            session["source"] = body["source"]
        if body.get("id") is not None:
            session["id"] = body["id"]
        db_started = time.monotonic()
        created = app.state.store.create_session(session)
        db_ms = (time.monotonic() - db_started) * 1000.0
        total_ms = (time.monotonic() - started) * 1000.0
        logger.info(
            "create_trace trace_id=%s agent=%s environment=%s workspace_id=%s "
            "project_id=%s db_ms=%.2f total_ms=%.2f",
            created.get("id"),
            created.get("agent"),
            created.get("environment"),
            created.get("workspace_id"),
            created.get("project_id"),
            db_ms,
            total_ms,
        )
        return JSONResponse({"trace": created}, status_code=201)

    @app.post("/api/traces/{id}/events")
    async def append_events(id: str, request: Request) -> JSONResponse:
        started = time.monotonic()
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        session = _require_session_in_workspace(id, ctx)
        body = await _json_body(request)
        events = _events_from_body(body)
        single_object = "events" not in body and bool(body)

        # Routing scope is assigned authoritatively from the authenticated
        # principal / the session row — never trusted from the client body.
        # The principal's workspace is canonical; project_id comes from the
        # api_key principal's project, falling back to the session's project
        # (console/server principals carry no project_id).
        scope_workspace_id = ctx.workspace_id
        scope_project_id = (
            ctx.project_id if ctx.project_id is not None else session.get("project_id")
        )

        accepted = 0
        rejected: list[dict[str, Any]] = []
        db_ms = 0.0

        for index, event in enumerate(events):
            # Envelope validation -> per-event 422 reason.
            try:
                schema.validate_event(event)
            except (TypeError, ValueError) as exc:
                if single_object and len(events) == 1:
                    raise _HTTPError(422, str(exc)) from exc
                rejected.append({**_event_ref(index, event), "reason": str(exc)})
                continue

            # Overwrite any client-supplied scope so an event cannot lie about
            # its tenant attribution or mis-route itself to another project's
            # stream (cross-workspace isolation).
            stored = {
                **event,
                "session_id": id,
                "workspace_id": scope_workspace_id,
                "project_id": scope_project_id,
            }

            db_started = time.monotonic()
            result = app.state.store.append_event(id, stored)
            db_ms += (time.monotonic() - db_started) * 1000.0
            if not result.accepted:
                # seq conflict (or other rejection) -> per-event reason, no drop
                # of valid siblings.
                rejected.append(
                    {
                        **_event_ref(index, event),
                        "reason": result.reason or result.status,
                    }
                )
                continue

            accepted += 1
            if result.status == "accepted":
                # Only publish first-seen events; duplicate replays are no-ops.
                app.state.hub.publish(ctx.workspace_id, stored)
                if stored.get("type") == "session_end":
                    summary = app.state.runtime.finalize_session(
                        _runtime_scope(session, id)
                    )
                    app.state.store.add_audit(
                        {
                            "workspace_id": session.get("workspace_id"),
                            "project_id": session.get("project_id"),
                            "action": "runtime_finalize",
                            "actor_kind": ctx.kind,
                            "metadata": summary,
                        }
                    )

        total_ms = (time.monotonic() - started) * 1000.0
        logger.info(
            "append_events trace_id=%s event_count=%d accepted=%d rejected=%d "
            "workspace_id=%s project_id=%s db_ms=%.2f total_ms=%.2f",
            id,
            len(events),
            accepted,
            len(rejected),
            scope_workspace_id,
            scope_project_id,
            db_ms,
            total_ms,
        )
        return JSONResponse(
            {"accepted": accepted, "rejected": rejected}, status_code=200
        )

    # -- agents ----------------------------------------------------------------

    @app.get("/api/agents")
    async def list_agents(request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        project_id = request.query_params.get("project_id")
        if project_id:
            _require_project_in_workspace(project_id, ctx)
        return {
            "agents": app.state.store.list_agents(
                workspace_id=ctx.workspace_id,
                project_id=project_id or None,
            )
        }

    @app.post("/api/agents")
    async def create_agent(request: Request) -> JSONResponse:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        body = await _json_body(request)
        name = _optional_text(body, "name", "", max_length=120)
        project_id = body.get("project_id")
        if project_id is not None and not isinstance(project_id, str):
            raise _HTTPError(400, "project_id must be a string")
        if project_id:
            _require_project_in_workspace(project_id, ctx)
        else:
            projects = app.state.store.list_projects(workspace_id=ctx.workspace_id)
            if not projects:
                raise _HTTPError(400, "create a project before creating an agent")
            project_id = str(projects[0]["id"])

        agent = app.state.store.create_agent(
            {
                "workspace_id": ctx.workspace_id,
                "project_id": project_id,
                "name": name,
            }
        )
        app.state.store.add_audit(
            {
                "workspace_id": ctx.workspace_id,
                "project_id": project_id,
                "action": "agent_create",
                "actor_kind": ctx.kind,
                "metadata": {"agent_id": agent.get("id"), "user_id": ctx.user_id},
            }
        )
        return JSONResponse({"agent": agent}, status_code=201)

    # -- agent runtime guidance -------------------------------------------------

    @app.post("/api/traces/{id}/runtime/memory")
    async def runtime_memory_add(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        session = _require_runtime_session(id, ctx)
        body = await _json_body(request)
        memory = app.state.runtime.add_memory(_runtime_scope(session, id), body)
        return {"memory": memory}

    @app.get("/api/traces/{id}/runtime/memory")
    async def runtime_memory_list(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        session = _require_runtime_session(id, ctx)
        limit_raw = request.query_params.get("limit", "20")
        try:
            limit = int(limit_raw)
        except ValueError:
            raise _HTTPError(400, "limit must be an integer")
        memory = app.state.runtime.list_memory(_runtime_scope(session, id), limit=limit)
        return {"memory": memory}

    @app.post("/api/traces/{id}/runtime/tool-call")
    async def runtime_tool_call(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        session = _require_runtime_session(id, ctx)
        body = await _json_body(request)
        result = app.state.runtime.record_tool_call(_runtime_scope(session, id), body)
        return result

    @app.post("/api/traces/{id}/runtime/heartbeat")
    async def runtime_heartbeat(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        session = _require_runtime_session(id, ctx)
        body = await _json_body(request)
        heartbeat = app.state.runtime.set_heartbeat(_runtime_scope(session, id), body)
        return {"heartbeat": heartbeat}

    @app.get("/api/traces/{id}/runtime/hint")
    async def runtime_hint(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        session = _require_runtime_session(id, ctx)
        hint = app.state.runtime.next_hint(_runtime_scope(session, id))
        return {"hint": hint}

    @app.post("/api/traces/{id}/artifacts")
    async def upload_artifact(id: str, request: Request) -> JSONResponse:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        session = _require_session_in_workspace(id, ctx)
        body, raw_body = await _artifact_body(request)

        content_type = str(body.get("content_type") or "")
        if content_type not in _ALLOWED_ARTIFACT_CONTENT_TYPES:
            raise _HTTPError(
                415, f"unsupported artifact content-type: {content_type!r}"
            )

        # Size enforcement is client-declared in State 0 (no real bytes yet),
        # but it must not be evadable by omitting/forging the field. Require a
        # non-negative integer size and reject anything else rather than
        # silently skipping the 413 gate (Storage Contract).
        size_bytes = body.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
            raise _HTTPError(413, "artifact size_bytes must be a non-negative integer")
        if size_bytes < 0:
            raise _HTTPError(413, "artifact size_bytes must be a non-negative integer")
        if size_bytes > _max_artifact_bytes():
            raise _HTTPError(413, "artifact exceeds maximum size")

        workspace_id = session.get("workspace_id") or ctx.workspace_id
        # The store mints the id when none is supplied; storage_path is derived after.
        filename = safe_artifact_filename(str(body.get("filename") or "artifact.bin"))
        artifact: dict[str, Any] = {
            "session_id": id,
            "workspace_id": workspace_id,
            "project_id": session.get("project_id"),
            "content_type": content_type,
            "size_bytes": size_bytes,
            "filename": filename,
            "artifact_type": body.get("artifact_type"),
        }
        if body.get("artifact_id") is not None:
            artifact["artifact_id"] = body["artifact_id"]

        created = app.state.store.add_artifact(artifact)
        # storage_path needs the minted artifact_id, so derive + persist it now.
        if raw_body is not None:
            stored_bytes = app.state.artifact_storage.put(
                workspace_id=str(workspace_id),
                session_id=id,
                artifact_id=str(created["artifact_id"]),
                filename=filename,
                body=raw_body,
                content_type=content_type,
            )
            created["storage_path"] = stored_bytes.storage_path
            created["size_bytes"] = stored_bytes.size_bytes
        else:
            created["storage_path"] = artifact_storage_path(
                workspace_id=str(workspace_id),
                session_id=id,
                artifact_id=str(created["artifact_id"]),
                filename=filename,
            )
        stored = app.state.store.add_artifact(created)
        return JSONResponse({"artifact": stored}, status_code=201)

    # -- console reads ----------------------------------------------------------

    @app.get("/api/sessions")
    async def list_sessions(request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        sessions = app.state.store.list_sessions(
            workspace_id=ctx.workspace_id,
            project_id=ctx.project_id if ctx.kind == "api_key" else None,
        )
        return {"sessions": sessions}

    @app.get("/api/traces/{id}/events")
    async def read_events(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        _require_session_read(id, ctx)
        return {"events": app.state.store.get_events(id)}

    @app.get("/api/traces/{id}/analysis")
    async def read_analysis(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        _require_session_read(id, ctx)
        return {"analysis": app.state.store.get_analysis(id)}

    @app.get("/api/projects")
    async def list_projects(request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        return {
            "workspace": {
                "id": ctx.workspace_id,
                "user_id": ctx.user_id,
                "role": ctx.role,
            },
            "projects": app.state.store.list_projects(workspace_id=ctx.workspace_id),
        }

    @app.post("/api/projects/{id}/api-key")
    async def rotate_project_api_key(id: str, request: Request) -> JSONResponse:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        _require_owner(ctx)
        project = _require_project_in_workspace(id, ctx)

        raw_key = generate_project_api_key()
        preview = api_key_preview(raw_key)
        updated = app.state.store.update_project(
            id,
            {
                "api_key_hash": hash_api_key(raw_key),
                "api_key_preview": preview,
                "api_key_rotated_at": _utc_now(),
            },
        )
        app.state.auth.replace_project_api_key(
            project_id=id,
            workspace_id=str(project.get("workspace_id") or ctx.workspace_id),
            api_key=raw_key,
        )
        app.state.store.add_audit(
            {
                "workspace_id": ctx.workspace_id,
                "project_id": project.get("id"),
                "action": "project_api_key_rotate",
                "actor_kind": ctx.kind,
                "metadata": {
                    "project_id": id,
                    "api_key_preview": preview,
                    "user_id": ctx.user_id,
                },
            }
        )
        return JSONResponse(
            {"project": updated, "api_key": raw_key, "api_key_preview": preview},
            status_code=201,
        )

    @app.patch("/api/projects/{id}")
    async def update_project(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        _require_owner(ctx)
        project = _require_project_in_workspace(id, ctx)
        body = await _json_body(request)

        patch: dict[str, Any] = {}
        if "retention_days" in body:
            retention_days = body["retention_days"]
            if (
                isinstance(retention_days, bool)
                or not isinstance(retention_days, int)
                or retention_days < 0
                or retention_days > 3650
            ):
                raise _HTTPError(400, "retention_days must be an integer from 0 to 3650")
            patch["retention_days"] = retention_days
        if "name" in body:
            name = body["name"]
            if not isinstance(name, str) or not name.strip():
                raise _HTTPError(400, "name must be a non-empty string")
            patch["name"] = name.strip()
        updated = app.state.store.update_project(id, patch)
        if patch:
            app.state.store.add_audit(
                {
                    "workspace_id": ctx.workspace_id,
                    "project_id": project.get("id"),
                    "action": "project_update",
                    "actor_kind": ctx.kind,
                    "metadata": {"patch": patch, "user_id": ctx.user_id},
                }
            )
        return {"project": updated}

    @app.put("/api/traces/{id}/analysis")
    async def store_analysis(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        if not ctx.is_server:
            raise _HTTPError(403, "analysis writeback is server-only")
        # Server principal is workspace-agnostic; require the row to exist.
        session = app.state.store.get_session(id)
        if session is None:
            raise _HTTPError(404, "trace not found")
        body = await _json_body(request)
        stored = app.state.store.set_analysis(id, body)
        return {"analysis": stored}

    @app.get("/artifacts/{artifact_id}")
    async def read_artifact(artifact_id: str, request: Request) -> Response:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        artifact = app.state.store.get_artifact(artifact_id)
        if artifact is None or (
            artifact.get("workspace_id") != ctx.workspace_id and not ctx.is_server
        ):
            raise _HTTPError(404, "artifact not found")
        storage_path = artifact.get("storage_path") or ""
        signed = {
            "artifact_id": artifact_id,
            "signed_url": app.state.artifact_storage.signed_url(
                str(storage_path), expires_in=300
            ),
            "expires_in": 300,
        }
        wants_json = request.query_params.get("format") == "json" or (
            "application/json" in request.headers.get("accept", "")
            and "text/html" not in request.headers.get("accept", "")
        )
        if wants_json:
            return JSONResponse(signed)
        return RedirectResponse(signed["signed_url"], status_code=307)

    # -- SSE stream -------------------------------------------------------------

    @app.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        project_id = request.query_params.get("project_id")
        session_id = request.query_params.get("session_id")
        after_seq_raw = request.query_params.get("after_seq")
        after_seq = None
        if after_seq_raw is not None:
            try:
                after_seq = int(after_seq_raw)
            except ValueError:
                raise _HTTPError(400, "after_seq must be an integer")

        hub: StreamHub = app.state.hub
        store_ref: Store = app.state.store
        workspace_id = ctx.workspace_id

        async def event_source() -> AsyncIterator[str]:
            # Backfill from the store first (events after after_seq), then go live.
            from promptetheus.server.stream import format_sse

            if session_id is not None:
                session = store_ref.get_session(session_id)
                if session is None or (
                    session.get("workspace_id") != workspace_id and not ctx.is_server
                ):
                    return
                for event in store_ref.get_events(session_id):
                    if after_seq is not None and event.get("seq", 0) <= after_seq:
                        continue
                    if (
                        project_id is not None
                        and str(event.get("project_id")) != project_id
                    ):
                        continue
                    yield format_sse(event)

            async for record in hub.subscribe(
                workspace_id, project_id=project_id, session_id=session_id
            ):
                if await request.is_disconnected():
                    break
                yield record

        return StreamingResponse(event_source(), media_type="text/event-stream")

    # -- analysis ---------------------------------------------------------------

    @app.post("/api/traces/{id}/analyze")
    async def analyze_trace(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        session = _require_session_in_workspace(id, ctx)
        events = app.state.store.get_events(id)

        result = analyze_session(session, events)
        analysis = result.as_dict()
        app.state.store.set_analysis(id, analysis)
        incidents = assemble_incidents(app.state.store, session, result)
        app.state.store.add_audit(
            {
                "workspace_id": session.get("workspace_id"),
                "project_id": session.get("project_id"),
                "action": "analyze",
                "session_id": id,
                "actor_kind": ctx.kind,
                "metadata": {
                    "labels": analysis.get("labels"),
                    "fallback": result.fallback,
                    "llm_enabled": classifier.analysis_llm_enabled(),
                },
            }
        )
        return {
            "analysis": analysis,
            "incidents": incidents,
            "fallback": result.fallback,
        }

    # -- incidents --------------------------------------------------------------

    @app.get("/api/incidents")
    async def list_incidents(request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        incidents = app.state.store.list_incidents(workspace_id=ctx.workspace_id)
        if ctx.kind == "api_key" and ctx.project_id is not None:
            incidents = [
                incident
                for incident in incidents
                if incident.get("project_id") == ctx.project_id
            ]
        query = request.query_params.get("q")
        if query:
            incidents = [
                incident
                for incident in incidents
                if _incident_matches(incident, query)
            ]
        return {"incidents": incidents}

    @app.get("/api/incidents/{id}")
    async def get_incident_route(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        incident = _require_incident_read(id, ctx)
        return {"incident": incident}

    @app.get("/api/incidents/{id}/context")
    async def get_incident_context_route(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("api_key", "console"))
        incident = _require_incident_read(id, ctx)
        context = build_incident_context(app.state.store, incident)
        return {"context": context}

    @app.get("/api/projects/{id}/connected-repo")
    async def get_connected_repo_route(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        # No connected-repo entity exists yet (stub). An api_key principal is
        # scoped to its own project; tell others the resource is absent (404)
        # rather than leak that a project id exists. Server/console principals
        # carry no project_id, so they always get the stub.
        if ctx.project_id is not None and ctx.project_id != id and not ctx.is_server:
            raise _HTTPError(404, "connected repo not found")
        return {"connected_repo": connected_repo_stub(id)}

    @app.post("/api/incidents/{id}/pr-link")
    async def link_incident_pr(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        incident = _require_incident_in_workspace(id, ctx)
        body = await _json_body(request)

        pr_url = body.get("pr_url")
        if not isinstance(pr_url, str) or not pr_url.strip():
            raise _HTTPError(400, "pr_url is required")

        updated = app.state.store.update_incident(id, {"pr_url": pr_url})
        app.state.store.add_audit(
            {
                "workspace_id": incident.get("workspace_id"),
                "project_id": incident.get("project_id"),
                "action": "incident_pr_link",
                "incident_id": id,
                "actor_kind": ctx.kind,
                "metadata": {"pr_url": pr_url},
            }
        )
        return {"incident": updated}

    @app.patch("/api/incidents/{id}")
    async def update_incident(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        _require_incident_in_workspace(id, ctx)
        body = await _json_body(request)

        patch: dict[str, Any] = {}
        if "status" in body:
            status = body["status"]
            if status not in INCIDENT_STATUSES:
                raise _HTTPError(400, f"invalid incident status: {status!r}")
            patch["status"] = status
        if "owner_id" in body:
            patch["owner_id"] = body["owner_id"]

        updated = app.state.store.update_incident(id, patch)
        return {"incident": updated}

    @app.post("/api/incidents/{id}/fix-agent")
    async def dispatch_fix_agent(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        incident = _require_incident_in_workspace(id, ctx)

        bundle = build_incident_bundle(app.state.store, incident)
        runner = get_runner(allowed_paths=bundle.get("allowed_paths"))
        try:
            fix_result = runner.run(bundle)
        except ValueError as exc:
            raise _HTTPError(400, str(exc)) from exc
        except NotImplementedError as exc:
            raise _HTTPError(501, str(exc)) from exc

        result_dict = fix_result.as_dict()
        github_pr: dict[str, Any] | None = None
        if github_pr_enabled() or github_fallback_forced():
            github_config = GitHubConfig.from_env()
            try:
                pr_result = create_pull_request(
                    fix_result=fix_result,
                    incident=incident,
                    bundle=bundle,
                    config=github_config,
                )
            except ValueError as exc:
                raise _HTTPError(400, str(exc)) from exc
            except Exception as exc:
                fallback_result = create_pull_request(
                    fix_result=fix_result,
                    incident=incident,
                    bundle=bundle,
                    config=replace(github_config, fallback=True, enabled=True),
                )
                pr_result = (
                    replace(
                        fallback_result,
                        metadata={
                            **fallback_result.metadata,
                            "fallback_reason": f"GitHub PR creation failed: {exc}",
                        },
                    )
                    if fallback_result is not None
                    else None
                )
            if pr_result is not None:
                github_pr = pr_result.as_dict()
                result_dict["github_pr"] = github_pr

        incident_patch: dict[str, Any] = {"fix_agent_result": result_dict}
        if github_pr is not None and github_pr.get("pr_url"):
            incident_patch["pr_url"] = github_pr["pr_url"]
        app.state.store.update_incident(id, incident_patch)
        app.state.store.add_audit(
            {
                "workspace_id": incident.get("workspace_id"),
                "project_id": incident.get("project_id"),
                "action": "fix_agent_dispatch",
                "incident_id": id,
                "actor_kind": ctx.kind,
                "metadata": result_dict,
            }
        )
        if github_pr is not None:
            app.state.store.add_audit(
                {
                    "workspace_id": incident.get("workspace_id"),
                    "project_id": incident.get("project_id"),
                    "action": "github_pr_create",
                    "incident_id": id,
                    "actor_kind": ctx.kind,
                    "metadata": github_pr,
                }
            )
        return {
            "incident_id": id,
            "plan": result_dict["plan"],
            "diff": result_dict["diff"],
            "metadata": result_dict["metadata"],
            "summary": result_dict.get("summary"),
            "changed_files": result_dict.get("changed_files"),
            "runner": result_dict.get("runner"),
            "confidence": result_dict.get("confidence"),
            "evidence_refs": result_dict.get("evidence_refs"),
            "fallback": result_dict.get("fallback", True),
            "github_pr": github_pr,
        }

    @app.post("/api/incidents/{id}/heal")
    async def heal_incident_endpoint(id: str, request: Request) -> dict[str, Any]:
        """Run the bounded self-healing loop for an incident.

        Diagnose -> verify (LLM critique + regression) up to the attempt cap, then
        open a PR and stop for a human to merge (or escalate if unverified). The
        orchestrator (in-process or Agentspan) is selected by env; the heal steps
        are the same callables either way.
        """

        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        incident = _require_incident_in_workspace(id, ctx)

        body = await _json_body(request)
        max_attempts = body.get("max_attempts") if isinstance(body, dict) else None
        if max_attempts is not None and (
            isinstance(max_attempts, bool) or not isinstance(max_attempts, int)
        ):
            raise _HTTPError(400, "max_attempts must be an integer")

        try:
            report = run_loop(app.state.store, incident, max_attempts=max_attempts)
        except ValueError as exc:
            raise _HTTPError(400, str(exc)) from exc

        app.state.store.add_audit(
            {
                "workspace_id": incident.get("workspace_id"),
                "project_id": incident.get("project_id"),
                "action": "heal_loop",
                "incident_id": id,
                "actor_kind": ctx.kind,
                "metadata": {
                    "status": report.status,
                    "attempts": report.attempts,
                    "source": report.source,
                    "orchestrator": report.orchestrator,
                    "workflow_run_id": report.workflow_run_id,
                },
            }
        )
        return report.as_dict()

    @app.post("/api/incidents/{id}/regression-runs")
    async def trigger_regression_run(id: str, request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))
        incident = _require_incident_in_workspace(id, ctx)
        body = await _json_body(request)
        pr_url = body.get("pr_url")
        fallback_profile = body.get("fallback_profile")

        run = run_regression(
            app.state.store,
            incident,
            pr_url=pr_url,
            fallback_profile=str(fallback_profile) if fallback_profile is not None else None,
        )
        app.state.store.add_audit(
            {
                "workspace_id": incident.get("workspace_id"),
                "project_id": incident.get("project_id"),
                "action": "regression_run",
                "incident_id": id,
                "actor_kind": ctx.kind,
                "regression_run_id": run.get("id"),
            }
        )
        return {"regression_run": run, "fallback": True}

    # -- evals scoreboard -------------------------------------------------------

    @app.get("/api/evals/scoreboard")
    async def eval_scoreboard(request: Request) -> dict[str, Any]:
        """Aggregate the LLM-as-judge eval verdicts across heals.

        Reads the persisted `heal_attempt` audit rows (which carry each
        attempt's eval verdict) and folds them into a per-incident scoreboard:
        the decisive (last) attempt's before/after pass, judge confidence, and
        whether the gate passed — plus workspace-level rollups. This is the read
        the console eval scoreboard renders; the same eval scores are emitted to
        Sentry in parallel for production observability.
        """

        ctx = _authenticate(request)
        _require_principal(ctx, ("console",))

        audits = app.state.store.list_audit(workspace_id=ctx.workspace_id)
        latest: dict[str, dict[str, Any]] = {}
        attempts_by_incident: dict[str, int] = {}
        for entry in audits:
            if entry.get("action") != "heal_attempt":
                continue
            meta = entry.get("metadata") or {}
            report = meta.get("eval")
            incident_id = entry.get("incident_id")
            if incident_id is None or not isinstance(report, dict):
                continue
            if not report.get("meaningful"):
                continue
            attempts_by_incident[incident_id] = attempts_by_incident.get(incident_id, 0) + 1
            latest[incident_id] = report  # append-ordered audits -> last wins

        labels: dict[str, str] = {}
        for incident in app.state.store.list_incidents(workspace_id=ctx.workspace_id):
            iid = incident.get("id")
            if iid is not None:
                labels[iid] = incident.get("label") or incident.get("title") or iid

        rows: list[dict[str, Any]] = []
        for incident_id, report in latest.items():
            cases = report.get("cases") or []
            case = cases[0] if isinstance(cases, list) and cases else {}
            rows.append(
                {
                    "incident_id": incident_id,
                    "label": labels.get(incident_id, incident_id),
                    "before_passed": bool(case.get("before_passed", False)),
                    "after_passed": bool(case.get("after_passed", True)),
                    "confidence": float(case.get("confidence") or 0.0),
                    "attempts": attempts_by_incident.get(incident_id, 1),
                    "fallback": bool(report.get("fallback")),
                    "passed": bool(report.get("passed")),
                    "reason": case.get("reason"),
                }
            )
        rows.sort(key=lambda row: row["incident_id"])

        total = len(rows)
        passed = sum(1 for row in rows if row["passed"])
        flips = sum(1 for row in rows if not row["before_passed"] and row["after_passed"])
        fallback_count = sum(1 for row in rows if row["fallback"])
        avg_confidence = (
            sum(row["confidence"] for row in rows) / total if total else 0.0
        )
        return {
            "scoreboard": {
                "total": total,
                "passed": passed,
                "pass_rate": (passed / total) if total else 0.0,
                "flips": flips,
                "avg_confidence": avg_confidence,
                "fallback_count": fallback_count,
                "rows": rows,
            }
        }

    # -- internal jobs ----------------------------------------------------------

    @app.post("/internal/retention/run")
    async def run_retention(request: Request) -> dict[str, Any]:
        ctx = _authenticate(request)
        _require_principal(ctx, ("server",))
        body = await _json_body(request)
        project_id = body.get("project_id")
        if project_id is not None and not isinstance(project_id, str):
            raise _HTTPError(400, "project_id must be a string")
        limit = body.get("limit", 100)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise _HTTPError(400, "limit must be a positive integer")
        dry_run = body.get("dry_run", True)
        if not isinstance(dry_run, bool):
            raise _HTTPError(400, "dry_run must be a boolean")

        result = run_retention_cleanup(
            store=app.state.store,
            artifact_storage=app.state.artifact_storage,
            project_id=project_id,
            limit=limit,
            dry_run=dry_run,
        )
        app.state.store.add_audit(
            {
                "workspace_id": ctx.workspace_id,
                "project_id": project_id,
                "action": "retention_cleanup",
                "actor_kind": ctx.kind,
                "metadata": result,
            }
        )
        return {"retention": result}

    # -- error mapping ----------------------------------------------------------

    @app.exception_handler(_HTTPError)
    async def _handle_http_error(_request: Request, exc: _HTTPError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app
