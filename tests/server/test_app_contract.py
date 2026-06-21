"""Contract tests for the State-0 FastAPI spine (the 14 locked endpoints).

These assert the *real* server behavior, not placeholders: route surface, auth
gating (401/403/404), per-event accept/reject + seq conflict, artifact 413/415,
analyze -> incident, fix-agent bundle, and regression before/after. Behavior is
frozen by server/INTERNAL_CONTRACT.md section 5 and the "API Contract" /
"Detector Semantics" sections of docs/architecture/technical-architecture.md.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server import create_app  # noqa: E402
from promptetheus.server.auth import AuthRegistry, WorkspaceMembership  # noqa: E402
from promptetheus.server.db.keys import lookup_project_by_api_key  # noqa: E402
from promptetheus.server.store import InMemoryStore  # noqa: E402


# Deterministic dev credentials wired by AuthRegistry (see auth.py).
KEY_AUTH = {"Authorization": "Bearer pt_dev_key"}  # api_key -> ws_dev / proj_dev
CONSOLE_AUTH = {"Authorization": "Bearer pt_console_token"}  # console -> ws_dev
SERVER_AUTH = {"Authorization": "Bearer pt_server_token"}  # server (ws-agnostic)


LOCKED_ENDPOINTS = {
    ("POST", "/api/traces"),
    ("POST", "/api/traces/{id}/events"),
    ("POST", "/api/traces/{id}/artifacts"),
    ("GET", "/api/sessions"),
    ("GET", "/api/traces/{id}/events"),
    ("GET", "/api/traces/{id}/analysis"),
    ("PUT", "/api/traces/{id}/analysis"),
    ("GET", "/api/stream"),
    ("GET", "/artifacts/{artifact_id}"),
    ("POST", "/api/traces/{id}/analyze"),
    ("GET", "/api/incidents"),
    ("PATCH", "/api/incidents/{id}"),
    ("POST", "/api/incidents/{id}/fix-agent"),
    ("POST", "/api/incidents/{id}/regression-runs"),
}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> testclient.TestClient:
    return testclient.TestClient(create_app())


def _event(
    *,
    seq: int,
    idempotency_key: str,
    event_type: str = "agent_message",
    session_id: str = "trace_1",
    payload: dict | None = None,
) -> dict:
    return {
        "type": event_type,
        "session_id": session_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "seq": seq,
        "idempotency_key": idempotency_key,
        "payload": payload or {},
    }


def _create_trace(client: testclient.TestClient, trace_id: str = "trace_1") -> str:
    response = client.post(
        "/api/traces",
        json={"user_goal": "Book a meeting room for Tuesday", "id": trace_id},
        headers=KEY_AUTH,
    )
    assert response.status_code == 201
    return response.json()["trace"]["id"]


def _supabase_client_for_fresh_user() -> tuple[testclient.TestClient, dict[str, str]]:
    jwt = pytest.importorskip("jwt")
    store = InMemoryStore()
    secret = "test-supabase-jwt-secret-with-32-bytes"
    user_id = str(uuid.uuid4())
    token = jwt.encode(
        {"sub": user_id, "aud": "authenticated"},
        secret,
        algorithm="HS256",
    )

    def membership_lookup(
        user_id: str, workspace_id: str | None
    ) -> WorkspaceMembership | None:
        row = store.find_workspace_membership(user_id=user_id, workspace_id=workspace_id)
        if row is None:
            return None
        return WorkspaceMembership(
            workspace_id=str(row["workspace_id"]),
            user_id=str(row["user_id"]),
            role=row["role"],
        )

    auth = AuthRegistry(
        project_lookup=lambda api_key: lookup_project_by_api_key(store, api_key),
        membership_lookup=membership_lookup,
        auth_mode="supabase",
        supabase_jwt_secret=secret,
    )
    return (
        testclient.TestClient(create_app(store=store, auth=auth)),
        {"Authorization": f"Bearer {token}"},
    )


def _failing_session_events(session_id: str = "trace_1") -> list[dict]:
    """An AcmeMeet-style failing booking that fires a detector + forms an incident.

    Picks Wednesday when the goal says Tuesday, ignores a UI warning, then claims
    success while goal_check.passed is False -> browser_goal_mismatch fires.
    """

    return [
        _event(seq=1, idempotency_key="e1", event_type="user_message", session_id=session_id,
               payload={"content": "Book a meeting room for Tuesday"}),
        _event(seq=2, idempotency_key="e2", event_type="browser_action", session_id=session_id,
               payload={"action": "click", "target": "#wednesday"}),
        _event(seq=3, idempotency_key="e3", event_type="dom_snapshot", session_id=session_id,
               payload={"selected_values": {"day": "Wednesday"}, "warnings": ["Room unavailable"]}),
        _event(seq=4, idempotency_key="e4", event_type="browser_action", session_id=session_id,
               payload={"action": "submit", "target": "#confirm"}),
        _event(seq=5, idempotency_key="e5", event_type="agent_message", session_id=session_id,
               payload={"content": "Done! Successfully booked."}),
        _event(seq=6, idempotency_key="e6", event_type="goal_check", session_id=session_id,
               payload={"passed": False, "mismatches": ["wrong day"]}),
        _event(seq=7, idempotency_key="e7", event_type="session_end", session_id=session_id,
               payload={"status": "success"}),
    ]


# ---------------------------------------------------------------------------
# Route surface + health
# ---------------------------------------------------------------------------


def test_health_unchanged(client: testclient.TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_self_host_dashboard_renders_persisted_trace(
    client: testclient.TestClient,
) -> None:
    session_id = _create_trace(client, trace_id="trace_self_host")
    appended = client.post(
        f"/api/traces/{session_id}/events",
        json={
            "events": [
                _event(
                    seq=1,
                    idempotency_key="self-host-user",
                    event_type="user_message",
                    session_id=session_id,
                    payload={"content": "smoke self-host dashboard"},
                ),
                _event(
                    seq=2,
                    idempotency_key="self-host-agent",
                    event_type="agent_message",
                    session_id=session_id,
                    payload={"content": "events landed"},
                ),
            ]
        },
        headers=KEY_AUTH,
    )
    assert appended.status_code == 200

    page = client.get("/self-host")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "Promptetheus Self-Host" in page.text
    assert "trace_self_host" in page.text
    assert "events landed" in page.text

    data = client.get("/self-host.json")
    assert data.status_code == 200
    body = data.json()
    assert body["session_count"] == 1
    assert body["event_count"] == 2
    assert body["selected_session"]["id"] == "trace_self_host"
    assert [event["seq"] for event in body["selected_events"]] == [1, 2]


def test_self_host_dashboard_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTETHEUS_SELF_HOST_DASHBOARD", "0")
    local_client = testclient.TestClient(create_app())

    response = local_client.get("/self-host")
    assert response.status_code == 404
    assert response.json() == {"detail": "self-host dashboard is disabled"}


def test_self_host_dashboard_disabled_for_non_memory_store_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROMPTETHEUS_SELF_HOST_DASHBOARD", raising=False)
    local_client = testclient.TestClient(create_app(store=object()))  # type: ignore[arg-type]

    response = local_client.get("/self-host")
    assert response.status_code == 404
    assert response.json() == {"detail": "self-host dashboard is disabled"}


def test_locked_endpoint_routes_exist() -> None:
    app = create_app()
    routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    assert LOCKED_ENDPOINTS <= routes


# ---------------------------------------------------------------------------
# Auth: 401 / 403 / cross-workspace
# ---------------------------------------------------------------------------


def test_missing_credential_is_401(client: testclient.TestClient) -> None:
    assert client.get("/api/sessions").status_code == 401
    assert client.post("/api/traces", json={"user_goal": "g"}).status_code == 401


def test_invalid_credential_is_401(client: testclient.TestClient) -> None:
    bad = {"Authorization": "Bearer not_a_real_token"}
    assert client.get("/api/sessions", headers=bad).status_code == 401


def test_api_key_principal_can_read_own_project_routes(
    client: testclient.TestClient,
) -> None:
    session_id = _create_trace(client)
    appended = client.post(
        f"/api/traces/{session_id}/events",
        json={"events": [_event(seq=1, idempotency_key="api-key-read")]},
        headers=KEY_AUTH,
    )
    assert appended.status_code == 200

    sessions = client.get("/api/sessions", headers=KEY_AUTH)
    assert sessions.status_code == 200
    assert [session["id"] for session in sessions.json()["sessions"]] == [session_id]

    events = client.get(f"/api/traces/{session_id}/events", headers=KEY_AUTH)
    assert events.status_code == 200
    assert [event["seq"] for event in events.json()["events"]] == [1]

    analysis = client.get(f"/api/traces/{session_id}/analysis", headers=KEY_AUTH)
    assert analysis.status_code == 200
    assert analysis.json()["analysis"] is None

    # Analysis execution is still a console workflow, not an API-key read.
    assert client.post(f"/api/traces/{session_id}/analyze", headers=KEY_AUTH).status_code == 403


def test_api_key_project_reads_are_project_scoped(
    client: testclient.TestClient,
) -> None:
    session_id = _create_trace(client, trace_id="trace_project_a")
    client.post(
        f"/api/traces/{session_id}/events",
        json={"events": [_event(seq=1, idempotency_key="project-a")]},
        headers=KEY_AUTH,
    )
    client.app.state.auth.register_project(
        project_id="proj_other", workspace_id="ws_dev", api_key="pt_other_project_key"
    )
    other_auth = {"Authorization": "Bearer pt_other_project_key"}
    other_trace = client.post(
        "/api/traces",
        json={"id": "trace_project_b", "user_goal": "Other project"},
        headers=other_auth,
    )
    assert other_trace.status_code == 201

    own_sessions = client.get("/api/sessions", headers=KEY_AUTH).json()["sessions"]
    other_sessions = client.get("/api/sessions", headers=other_auth).json()["sessions"]
    assert [session["id"] for session in own_sessions] == ["trace_project_a"]
    assert [session["id"] for session in other_sessions] == ["trace_project_b"]

    assert client.get(f"/api/traces/{session_id}/events", headers=other_auth).status_code == 404
    assert client.get("/api/traces/trace_project_b/events", headers=KEY_AUTH).status_code == 404


def test_api_key_principal_cannot_trigger_console_incident_workflows(
    client: testclient.TestClient,
) -> None:
    incident_id = _make_incident(client)

    assert (
        client.post(
            f"/api/incidents/{incident_id}/fix-agent", json={}, headers=KEY_AUTH
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/incidents/{incident_id}/regression-runs",
            json={},
            headers=KEY_AUTH,
        ).status_code
        == 403
    )


def test_put_analysis_by_non_server_principal_is_403(
    client: testclient.TestClient,
) -> None:
    session_id = _create_trace(client)
    # console + api_key principals are not the server writeback principal.
    assert (
        client.put(f"/api/traces/{session_id}/analysis", json={}, headers=CONSOLE_AUTH).status_code
        == 403
    )
    assert (
        client.put(f"/api/traces/{session_id}/analysis", json={}, headers=KEY_AUTH).status_code
        == 403
    )
    # The server principal is allowed.
    ok = client.put(
        f"/api/traces/{session_id}/analysis",
        json={"trace_id": session_id, "labels": []},
        headers=SERVER_AUTH,
    )
    assert ok.status_code == 200


def test_cross_workspace_access_is_denied(client: testclient.TestClient) -> None:
    """A foreign-workspace principal must not reach another workspace's rows.

    Per the frozen contract (app.py + INTERNAL_CONTRACT.md 404 row), a non-server
    principal in another workspace is told the row is *not found* (404) rather than
    forbidden, so it cannot even learn the row exists.
    """

    session_id = _create_trace(client)  # lives in ws_dev
    # Register a second workspace and a console token scoped to it.
    auth = client.app.state.auth
    auth.register_console_token("pt_other_console", "ws_other")
    other = {"Authorization": "Bearer pt_other_console"}

    assert client.get(f"/api/traces/{session_id}/events", headers=other).status_code == 404
    assert client.get(f"/api/traces/{session_id}/analysis", headers=other).status_code == 404
    # And the cross-workspace caller sees none of ws_dev's sessions.
    assert client.get("/api/sessions", headers=other).json()["sessions"] == []


# ---------------------------------------------------------------------------
# Traces + sessions
# ---------------------------------------------------------------------------


def test_create_trace_then_list_session(client: testclient.TestClient) -> None:
    response = client.post(
        "/api/traces",
        json={"user_goal": "Book Tuesday", "id": "trace_1"},
        headers=KEY_AUTH,
    )
    assert response.status_code == 201
    trace = response.json()["trace"]
    assert trace["id"] == "trace_1"
    # Stamped with the api-key principal's workspace/project.
    assert trace["workspace_id"] == "ws_dev"
    assert trace["project_id"] == "proj_dev"

    listed = client.get("/api/sessions", headers=CONSOLE_AUTH)
    assert listed.status_code == 200
    ids = [session["id"] for session in listed.json()["sessions"]]
    assert "trace_1" in ids


def test_project_settings_list_rotate_and_reuse_new_key(
    client: testclient.TestClient,
) -> None:
    listed = client.get("/api/projects", headers=CONSOLE_AUTH)
    assert listed.status_code == 200
    projects = listed.json()["projects"]
    assert projects
    assert projects[0]["id"] == "proj_dev"
    assert "api_key_hash" not in projects[0]

    rotated = client.post("/api/projects/proj_dev/api-key", headers=CONSOLE_AUTH)
    assert rotated.status_code == 201
    body = rotated.json()
    raw_key = body["api_key"]
    assert raw_key.startswith("pt_live_")
    assert body["api_key_preview"].endswith(raw_key[-6:])
    assert body["project"]["api_key_preview"] == body["api_key_preview"]
    assert "api_key_hash" not in body["project"]

    created = client.post(
        "/api/traces",
        json={"id": "trace_rotated", "user_goal": "Use rotated key"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert created.status_code == 201
    assert created.json()["trace"]["project_id"] == "proj_dev"


def test_supabase_user_bootstrap_can_create_agent_and_ingest_events() -> None:
    client, console_auth = _supabase_client_for_fresh_user()

    bootstrap = client.post(
        "/api/onboarding/bootstrap",
        json={
            "workspace_name": "Acme QA",
            "project_name": "Agent Runs",
            "agent_name": "browser-agent",
        },
        headers=console_auth,
    )
    assert bootstrap.status_code == 201
    body = bootstrap.json()
    raw_key = body["api_key"]
    assert raw_key.startswith("pt_live_")
    assert body["created_workspace"] is True
    assert body["created_project"] is True
    assert body["api_key_created"] is True
    assert body["agent"]["name"] == "browser-agent"

    listed_projects = client.get("/api/projects", headers=console_auth)
    assert listed_projects.status_code == 200
    assert [project["id"] for project in listed_projects.json()["projects"]] == [
        body["project"]["id"]
    ]

    created_trace = client.post(
        "/api/traces",
        json={
            "id": "trace_bootstrap",
            "agent": "browser-agent",
            "user_goal": "Book the Tuesday room",
            "environment": "preview",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert created_trace.status_code == 201
    assert created_trace.json()["trace"]["project_id"] == body["project"]["id"]

    appended = client.post(
        "/api/traces/trace_bootstrap/events",
        json={
            "events": [
                _event(
                    seq=1,
                    idempotency_key="bootstrap-user",
                    event_type="user_message",
                    session_id="trace_bootstrap",
                    payload={"content": "Book the Tuesday room"},
                ),
                _event(
                    seq=2,
                    idempotency_key="bootstrap-agent",
                    event_type="agent_message",
                    session_id="trace_bootstrap",
                    payload={"content": "Opening calendar"},
                ),
            ]
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert appended.status_code == 200
    assert appended.json() == {"accepted": 2, "rejected": []}

    events = client.get("/api/traces/trace_bootstrap/events", headers=console_auth)
    assert events.status_code == 200
    assert [event["seq"] for event in events.json()["events"]] == [1, 2]


def test_console_can_create_and_list_agents(client: testclient.TestClient) -> None:
    created = client.post(
        "/api/agents",
        json={"name": "voice-agent", "project_id": "proj_dev"},
        headers=CONSOLE_AUTH,
    )
    assert created.status_code == 201
    assert created.json()["agent"]["name"] == "voice-agent"

    listed = client.get("/api/agents?project_id=proj_dev", headers=CONSOLE_AUTH)
    assert listed.status_code == 200
    assert [agent["name"] for agent in listed.json()["agents"]] == ["voice-agent"]


def test_project_settings_mutations_require_owner_role(
    client: testclient.TestClient,
) -> None:
    client.app.state.auth.register_console_token(
        "pt_member_console", "ws_dev", user_id="user_member", role="member"
    )
    member = {"Authorization": "Bearer pt_member_console"}

    assert client.get("/api/projects", headers=member).status_code == 200
    assert client.post("/api/projects/proj_dev/api-key", headers=member).status_code == 403
    assert (
        client.patch(
            "/api/projects/proj_dev",
            json={"retention_days": 60},
            headers=member,
        ).status_code
        == 403
    )


def test_project_retention_update_validates_and_audits(
    client: testclient.TestClient,
) -> None:
    ok = client.patch(
        "/api/projects/proj_dev",
        json={"retention_days": 60},
        headers=CONSOLE_AUTH,
    )
    assert ok.status_code == 200
    assert ok.json()["project"]["retention_days"] == 60

    immediate = client.patch(
        "/api/projects/proj_dev",
        json={"retention_days": 0},
        headers=CONSOLE_AUTH,
    )
    assert immediate.status_code == 200
    assert immediate.json()["project"]["retention_days"] == 0

    bad = client.patch(
        "/api/projects/proj_dev",
        json={"retention_days": -1},
        headers=CONSOLE_AUTH,
    )
    assert bad.status_code == 400

    audit = client.app.state.store.list_audit(workspace_id="ws_dev")
    assert any(row.get("action") == "project_update" for row in audit)


# ---------------------------------------------------------------------------
# Per-event accept / reject + seq conflict
# ---------------------------------------------------------------------------


def test_append_events_per_event_accept_and_reject(client: testclient.TestClient) -> None:
    session_id = _create_trace(client)

    valid_late = _event(seq=2, idempotency_key="event_2", session_id=session_id)
    invalid_type = _event(seq=3, idempotency_key="event_3", session_id=session_id)
    invalid_type["type"] = "not_real"
    valid_early = _event(seq=1, idempotency_key="event_1", session_id=session_id)
    seq_conflict = _event(seq=1, idempotency_key="event_conflict", session_id=session_id)

    response = client.post(
        f"/api/traces/{session_id}/events",
        json={"events": [valid_late, invalid_type, valid_early, seq_conflict]},
        headers=KEY_AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    # The two valid events survive; the bad-type and seq-conflict events are rejected.
    assert body["accepted"] == 2
    rejected = body["rejected"]
    assert {entry["index"] for entry in rejected} == {1, 3}
    by_index = {entry["index"]: entry for entry in rejected}
    assert by_index[1]["idempotency_key"] == "event_3"
    assert "not_real" in by_index[1]["reason"]
    assert by_index[3]["idempotency_key"] == "event_conflict"
    assert "seq" in by_index[3]["reason"]

    # Valid events were stored and are returned ordered by seq.
    events = client.get(f"/api/traces/{session_id}/events", headers=CONSOLE_AUTH).json()["events"]
    assert [event["seq"] for event in events] == [1, 2]
    assert {event["idempotency_key"] for event in events} == {"event_1", "event_2"}


def test_append_accepts_bare_single_event(client: testclient.TestClient) -> None:
    session_id = _create_trace(client)
    response = client.post(
        f"/api/traces/{session_id}/events",
        json=_event(seq=1, idempotency_key="solo", session_id=session_id),
        headers=KEY_AUTH,
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "rejected": []}


# ---------------------------------------------------------------------------
# Artifacts: 413 (oversized) + 415 (bad content-type)
# ---------------------------------------------------------------------------


def test_artifact_unsupported_content_type_is_415(client: testclient.TestClient) -> None:
    session_id = _create_trace(client)
    response = client.post(
        f"/api/traces/{session_id}/artifacts",
        json={"content_type": "text/plain", "filename": "notes.txt", "size_bytes": 10},
        headers=KEY_AUTH,
    )
    assert response.status_code == 415


def test_artifact_oversized_is_413(client: testclient.TestClient) -> None:
    session_id = _create_trace(client)
    response = client.post(
        f"/api/traces/{session_id}/artifacts",
        json={
            "content_type": "image/png",
            "filename": "huge.png",
            "size_bytes": 10 * 1024 * 1024 * 1024,  # 10 GiB > 50 MiB limit
        },
        headers=KEY_AUTH,
    )
    assert response.status_code == 413


def test_artifact_within_limits_is_created(client: testclient.TestClient) -> None:
    session_id = _create_trace(client)
    response = client.post(
        f"/api/traces/{session_id}/artifacts",
        json={"content_type": "image/png", "filename": "ok.png", "size_bytes": 1024},
        headers=KEY_AUTH,
    )
    assert response.status_code == 201
    artifact = response.json()["artifact"]
    assert artifact["storage_path"].startswith(f"artifacts/ws_dev/{session_id}/")
    assert artifact["storage_path"].endswith("/ok.png")


# ---------------------------------------------------------------------------
# Analyze -> analysis row + incident
# ---------------------------------------------------------------------------


def test_analyze_produces_analysis_and_incident(client: testclient.TestClient) -> None:
    session_id = _create_trace(client)
    client.post(
        f"/api/traces/{session_id}/events",
        json={"events": _failing_session_events(session_id)},
        headers=KEY_AUTH,
    )

    response = client.post(f"/api/traces/{session_id}/analyze", headers=CONSOLE_AUTH)
    assert response.status_code == 200
    body = response.json()
    analysis = body["analysis"]

    # Back-compat fields required by the locked contract.
    assert analysis["trace_id"] == session_id
    assert "browser_goal_mismatch" in analysis["labels"]
    assert analysis["critical_step_seq"] is not None
    assert analysis["confidence"] > 0.0

    # The analysis is persisted and readable.
    stored = client.get(f"/api/traces/{session_id}/analysis", headers=CONSOLE_AUTH).json()
    assert stored["analysis"]["labels"] == analysis["labels"]

    # An incident is formed and listed.
    incidents = body["incidents"]
    assert incidents
    listed = client.get("/api/incidents", headers=CONSOLE_AUTH).json()["incidents"]
    listed_ids = {incident["id"] for incident in listed}
    assert {incident["id"] for incident in incidents} <= listed_ids
    primary = listed[0]
    assert primary["workspace_id"] == "ws_dev"
    assert primary["status"] == "new"


# ---------------------------------------------------------------------------
# Incident workflow: PATCH status, fix-agent, regression
# ---------------------------------------------------------------------------


def _make_incident(client: testclient.TestClient) -> str:
    session_id = _create_trace(client)
    client.post(
        f"/api/traces/{session_id}/events",
        json={"events": _failing_session_events(session_id)},
        headers=KEY_AUTH,
    )
    incidents = client.post(f"/api/traces/{session_id}/analyze", headers=CONSOLE_AUTH).json()[
        "incidents"
    ]
    assert incidents
    return incidents[0]["id"]


def test_patch_incident_status_valid_and_invalid(client: testclient.TestClient) -> None:
    incident_id = _make_incident(client)

    ok = client.patch(
        f"/api/incidents/{incident_id}", json={"status": "triaged"}, headers=CONSOLE_AUTH
    )
    assert ok.status_code == 200
    assert ok.json()["incident"]["status"] == "triaged"

    bad = client.patch(
        f"/api/incidents/{incident_id}", json={"status": "not_a_status"}, headers=CONSOLE_AUTH
    )
    assert bad.status_code == 400


def test_fix_agent_returns_plan_diff_metadata(client: testclient.TestClient) -> None:
    incident_id = _make_incident(client)

    response = client.post(
        f"/api/incidents/{incident_id}/fix-agent", json={}, headers=CONSOLE_AUTH
    )
    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"] == incident_id
    assert isinstance(body["plan"], list) and body["plan"]
    # A well-formed unified diff confined to allowed paths.
    assert "--- " in body["diff"] and "+++ b/" in body["diff"] and "@@" in body["diff"]
    assert body["metadata"]["fallback"] is True
    assert body["metadata"]["branch"].startswith("promptetheus/")


def test_regression_run_returns_before_after(client: testclient.TestClient) -> None:
    incident_id = _make_incident(client)

    response = client.post(
        f"/api/incidents/{incident_id}/regression-runs", json={}, headers=CONSOLE_AUTH
    )
    assert response.status_code == 200
    run = response.json()["regression_run"]
    assert run["incident_id"] == incident_id
    # State-0 fallback: every affected session flips from fail -> pass.
    assert run["before_pass"] == 0
    assert run["before_fail"] >= 1
    assert run["after_fail"] == 0
    assert run["after_pass"] == run["before_fail"]
    assert run["fallback"] is True


def test_regression_run_accepts_demo_fallback_profile(
    client: testclient.TestClient,
) -> None:
    incident_id = _make_incident(client)

    response = client.post(
        f"/api/incidents/{incident_id}/regression-runs",
        json={"fallback_profile": "demo"},
        headers=CONSOLE_AUTH,
    )

    assert response.status_code == 200
    run = response.json()["regression_run"]
    assert run["after_fail"] <= 1
    assert run["user_confirm_count"] >= 0


# ---------------------------------------------------------------------------
# MCP-facing additive routes: single incident, context bundle, search,
# connected-repo stub, pr-link write + audit (P30.7 / P30.7b)
# ---------------------------------------------------------------------------


def test_get_single_incident(client: testclient.TestClient) -> None:
    incident_id = _make_incident(client)

    ok = client.get(f"/api/incidents/{incident_id}", headers=CONSOLE_AUTH)
    assert ok.status_code == 200
    incident = ok.json()["incident"]
    assert incident["id"] == incident_id
    assert incident["workspace_id"] == "ws_dev"

    # Missing credential -> 401; unknown id -> 404.
    assert client.get(f"/api/incidents/{incident_id}").status_code == 401
    assert client.get("/api/incidents/nope", headers=CONSOLE_AUTH).status_code == 404


def test_api_key_can_read_own_project_incident_context(
    client: testclient.TestClient,
) -> None:
    incident_id = _make_incident(client)

    listed = client.get("/api/incidents", headers=KEY_AUTH)
    assert listed.status_code == 200
    incidents = listed.json()["incidents"]
    assert incident_id in {incident["id"] for incident in incidents}
    assert {incident["project_id"] for incident in incidents} == {"proj_dev"}

    incident = client.get(f"/api/incidents/{incident_id}", headers=KEY_AUTH)
    assert incident.status_code == 200
    assert incident.json()["incident"]["id"] == incident_id

    context = client.get(f"/api/incidents/{incident_id}/context", headers=KEY_AUTH)
    assert context.status_code == 200
    assert context.json()["context"]["incident"]["id"] == incident_id


def test_api_key_incident_reads_are_project_scoped(
    client: testclient.TestClient,
) -> None:
    own_incident_id = _make_incident(client)
    client.app.state.auth.register_project(
        project_id="proj_other", workspace_id="ws_dev", api_key="pt_other_project_key"
    )
    other_incident = client.app.state.store.upsert_incident(
        {
            "id": "incident_other_project",
            "workspace_id": "ws_dev",
            "project_id": "proj_other",
            "label": "other_project_failure",
            "title": "Other project failure",
            "severity": "medium",
            "status": "new",
            "representative_session_id": "trace_other",
        }
    )
    other_auth = {"Authorization": "Bearer pt_other_project_key"}

    own_list = client.get("/api/incidents", headers=KEY_AUTH).json()["incidents"]
    other_list = client.get("/api/incidents", headers=other_auth).json()["incidents"]
    assert own_incident_id in {incident["id"] for incident in own_list}
    assert {incident["project_id"] for incident in own_list} == {"proj_dev"}
    assert [incident["id"] for incident in other_list] == [other_incident["id"]]

    assert client.get(f"/api/incidents/{own_incident_id}", headers=other_auth).status_code == 404
    assert client.get(f"/api/incidents/{other_incident['id']}", headers=KEY_AUTH).status_code == 404


def test_get_single_incident_cross_workspace_is_404(
    client: testclient.TestClient,
) -> None:
    incident_id = _make_incident(client)  # lives in ws_dev
    client.app.state.auth.register_console_token("pt_other_console", "ws_other")
    other = {"Authorization": "Bearer pt_other_console"}
    assert client.get(f"/api/incidents/{incident_id}", headers=other).status_code == 404


def test_incident_context_bundle_shape(client: testclient.TestClient) -> None:
    incident_id = _make_incident(client)
    # Attach a replay recording for the representative session ("trace_1").
    artifact = client.post(
        "/api/traces/trace_1/artifacts",
        json={
            "content_type": "video/webm",
            "filename": "replay.webm",
            "size_bytes": 2048,
            "artifact_type": "replay",
        },
        headers=KEY_AUTH,
    )
    assert artifact.status_code == 201

    response = client.get(f"/api/incidents/{incident_id}/context", headers=CONSOLE_AUTH)
    assert response.status_code == 200
    context = response.json()["context"]

    assert context["incident"]["id"] == incident_id
    assert "browser_goal_mismatch" in context["labels"]
    assert context["evidence"], "evidence chips should be present"
    assert all("label" in chip for chip in context["evidence"])

    replay = context["replay"]
    assert replay["signed_url"].startswith("https://artifacts.local/signed/")
    assert "artifacts/ws_dev/trace_1/" in replay["signed_url"]
    assert replay["expires_in"] == 300
    # event_time_map keys are seqs (strings); the failing session has seq 1.
    assert "1" in replay["event_time_map"]

    repo = context["connected_repo"]
    assert repo["project_id"] == "proj_dev"
    assert repo["allowed_paths"] == ["agents/"]
    assert repo["stub"] is True

    # No regression yet -> regression_case is None until a run is triggered.
    assert context["regression_case"] is None


def test_incident_context_includes_latest_regression(
    client: testclient.TestClient,
) -> None:
    incident_id = _make_incident(client)
    client.post(
        f"/api/incidents/{incident_id}/regression-runs", json={}, headers=CONSOLE_AUTH
    )

    context = client.get(
        f"/api/incidents/{incident_id}/context", headers=CONSOLE_AUTH
    ).json()["context"]
    case = context["regression_case"]
    assert case is not None
    assert case["incident_id"] == incident_id
    assert case["after_fail"] == 0


def test_search_incidents_filter(client: testclient.TestClient) -> None:
    _make_incident(client)

    # Case-insensitive substring match over the incident label.
    hit = client.get("/api/incidents", params={"q": "BROWSER"}, headers=CONSOLE_AUTH)
    assert hit.status_code == 200
    labels = {incident["label"] for incident in hit.json()["incidents"]}
    assert "browser_goal_mismatch" in labels

    miss = client.get(
        "/api/incidents", params={"q": "no_such_label"}, headers=CONSOLE_AUTH
    )
    assert miss.json()["incidents"] == []

    # No filter -> full workspace listing is unchanged.
    all_incidents = client.get("/api/incidents", headers=CONSOLE_AUTH).json()["incidents"]
    assert all_incidents


def test_connected_repo_stub(client: testclient.TestClient) -> None:
    response = client.get("/api/projects/proj_dev/connected-repo", headers=KEY_AUTH)
    assert response.status_code == 200
    repo = response.json()["connected_repo"]
    assert repo["project_id"] == "proj_dev"
    assert repo["allowed_paths"] == ["agents/"]
    assert repo["stub"] is True
    assert repo["repo"] is None

    # Missing credential -> 401.
    assert client.get("/api/projects/proj_dev/connected-repo").status_code == 401


def test_pr_link_writes_and_audits(client: testclient.TestClient) -> None:
    incident_id = _make_incident(client)
    pr_url = "https://github.com/acme/repo/pull/42"

    response = client.post(
        f"/api/incidents/{incident_id}/pr-link",
        json={"pr_url": pr_url},
        headers=CONSOLE_AUTH,
    )
    assert response.status_code == 200
    assert response.json()["incident"]["pr_url"] == pr_url

    # The write is visible on the incident row.
    incident = client.get(
        f"/api/incidents/{incident_id}", headers=CONSOLE_AUTH
    ).json()["incident"]
    assert incident["pr_url"] == pr_url

    # An audit row is recorded for the link.
    audit = client.app.state.store.list_audit(workspace_id="ws_dev")
    pr_audits = [row for row in audit if row.get("action") == "incident_pr_link"]
    assert pr_audits
    assert pr_audits[-1]["incident_id"] == incident_id
    assert pr_audits[-1]["metadata"]["pr_url"] == pr_url


def test_pr_link_validation_and_auth(client: testclient.TestClient) -> None:
    incident_id = _make_incident(client)

    # Missing pr_url -> 400.
    bad = client.post(
        f"/api/incidents/{incident_id}/pr-link", json={}, headers=CONSOLE_AUTH
    )
    assert bad.status_code == 400

    # Unknown incident -> 404; missing credential -> 401.
    assert (
        client.post(
            "/api/incidents/nope/pr-link",
            json={"pr_url": "https://x/y/pull/1"},
            headers=CONSOLE_AUTH,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/incidents/{incident_id}/pr-link", json={"pr_url": "https://x/y/1"}
        ).status_code
        == 401
    )


def test_single_malformed_event_returns_422(client: testclient.TestClient) -> None:
    session_id = _create_trace(client, "trace_422")
    response = client.post(
        f"/api/traces/{session_id}/events",
        json={
            "type": "not_a_real_type",
            "session_id": session_id,
            "timestamp": "2026-01-01T00:00:00Z",
            "seq": 0,
            "idempotency_key": "bad",
            "payload": {},
        },
        headers=KEY_AUTH,
    )
    assert response.status_code == 422


def test_list_sessions_includes_analysis_labels(client: testclient.TestClient) -> None:
    session_id = _create_trace(client, "trace_labels")
    client.post(
        f"/api/traces/{session_id}/events",
        json={"events": _failing_session_events(session_id)},
        headers=KEY_AUTH,
    )
    client.post(f"/api/traces/{session_id}/analyze", headers=CONSOLE_AUTH)
    listed = client.get("/api/sessions", headers=CONSOLE_AUTH).json()["sessions"]
    row = next(item for item in listed if item["id"] == session_id)
    assert "browser_goal_mismatch" in row.get("labels", [])


def test_api_contract_sample_shapes(client: testclient.TestClient) -> None:
    import json
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "api_contract_samples.json"
    samples = json.loads(fixtures.read_text(encoding="utf-8"))

    created = client.post(
        "/api/traces",
        json=samples["create_trace"]["request"],
        headers=KEY_AUTH,
    )
    assert created.status_code == samples["create_trace"]["status"]
    trace = created.json()["trace"]
    assert "id" in trace and "workspace_id" in trace

    batch = client.post(
        f"/api/traces/{trace['id']}/events",
        json=samples["append_events_batch"]["request"],
        headers=KEY_AUTH,
    )
    assert batch.status_code == samples["append_events_batch"]["status"]
    assert "accepted" in batch.json()


# ---------------------------------------------------------------------------
# Eval scoreboard (GET /api/evals/scoreboard)
# ---------------------------------------------------------------------------


def test_eval_scoreboard_aggregates_heal_attempts(
    client: testclient.TestClient, monkeypatch
) -> None:
    # No key -> the eval gate uses its deterministic before-fail/after-pass
    # fallback, which is still a meaningful, scoreboard-able verdict.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    incident_id = _make_incident(client)

    healed = client.post(
        f"/api/incidents/{incident_id}/heal", json={}, headers=CONSOLE_AUTH
    )
    assert healed.status_code == 200

    board = client.get("/api/evals/scoreboard", headers=CONSOLE_AUTH)
    assert board.status_code == 200
    scoreboard = board.json()["scoreboard"]

    assert scoreboard["total"] >= 1
    assert scoreboard["flips"] >= 1
    row = next(r for r in scoreboard["rows"] if r["incident_id"] == incident_id)
    assert row["before_passed"] is False
    assert row["after_passed"] is True
    assert 0.0 <= row["confidence"] <= 1.0


def test_eval_scoreboard_is_console_only(client: testclient.TestClient) -> None:
    assert client.get("/api/evals/scoreboard", headers=KEY_AUTH).status_code == 403
