from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server import create_app  # noqa: E402
from promptetheus.server.runtime import (  # noqa: E402
    InMemoryRuntimeStore,
    NoopRuntimeStore,
    runtime_from_env,
)


KEY_AUTH = {"Authorization": "Bearer pt_dev_key"}
CONSOLE_AUTH = {"Authorization": "Bearer pt_console_token"}


@pytest.fixture()
def client() -> testclient.TestClient:
    return testclient.TestClient(create_app(runtime_store=InMemoryRuntimeStore()))


def _create_trace(client: testclient.TestClient, trace_id: str = "trace_runtime") -> str:
    response = client.post(
        "/api/traces",
        json={"user_goal": "debug runtime", "id": trace_id},
        headers=KEY_AUTH,
    )
    assert response.status_code == 201
    return response.json()["trace"]["id"]


def _event(session_id: str, seq: int, event_type: str, payload: dict) -> dict:
    return {
        "type": event_type,
        "session_id": session_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "seq": seq,
        "idempotency_key": f"{session_id}:runtime:{seq}",
        "payload": payload,
    }


def test_runtime_routes_require_auth(client: testclient.TestClient) -> None:
    assert client.get("/api/traces/missing/runtime/memory").status_code == 401
    assert client.post("/api/traces/missing/runtime/tool-call", json={}).status_code == 401


def test_runtime_missing_trace_is_404(client: testclient.TestClient) -> None:
    response = client.get("/api/traces/nope/runtime/memory", headers=CONSOLE_AUTH)

    assert response.status_code == 404


def test_runtime_project_isolation(client: testclient.TestClient) -> None:
    session_id = _create_trace(client)
    client.app.state.auth.register_project(
        project_id="proj_other",
        workspace_id="ws_dev",
        api_key="pt_other_key",
    )
    other_project = {"Authorization": "Bearer pt_other_key"}

    response = client.get(
        f"/api/traces/{session_id}/runtime/memory",
        headers=other_project,
    )

    assert response.status_code == 404


def test_runtime_memory_preserves_order_limit_and_redacts(
    client: testclient.TestClient,
) -> None:
    session_id = _create_trace(client)

    for index in range(3):
        response = client.post(
            f"/api/traces/{session_id}/runtime/memory",
            json={
                "kind": "hypothesis",
                "value": {
                    "index": index,
                    "note": "token sk-ABCDEFabcdef0123456789",
                },
            },
            headers=KEY_AUTH,
        )
        assert response.status_code == 200

    response = client.get(
        f"/api/traces/{session_id}/runtime/memory?limit=2",
        headers=CONSOLE_AUTH,
    )

    assert response.status_code == 200
    memory = response.json()["memory"]
    assert [item["value"]["index"] for item in memory] == [1, 2]
    assert "sk-ABCDEF" not in memory[-1]["value"]["note"]


def test_runtime_tool_call_repeated_failure_returns_hint(
    client: testclient.TestClient,
) -> None:
    session_id = _create_trace(client)
    payload = {
        "tool_name": "pytest",
        "command": "pytest tests/server",
        "args": {"path": "tests/server"},
        "status": "failed",
        "error": "assertion failed",
    }

    first = client.post(
        f"/api/traces/{session_id}/runtime/tool-call",
        json=payload,
        headers=KEY_AUTH,
    )
    second = client.post(
        f"/api/traces/{session_id}/runtime/tool-call",
        json=payload,
        headers=KEY_AUTH,
    )
    hint = client.get(
        f"/api/traces/{session_id}/runtime/hint",
        headers=CONSOLE_AUTH,
    )

    assert first.status_code == 200
    assert first.json()["seen_recently"] is False
    assert second.status_code == 200
    assert second.json()["seen_recently"] is True
    assert second.json()["failure_count"] == 2
    assert second.json()["hint"]["kind"] == "repeated_tool_failure"
    assert hint.json()["hint"]["kind"] == "repeated_tool_failure"


def test_runtime_heartbeat_updates_live_state(client: testclient.TestClient) -> None:
    session_id = _create_trace(client)

    response = client.post(
        f"/api/traces/{session_id}/runtime/heartbeat",
        json={"phase": "debugging", "current_file": "server/app.py"},
        headers=KEY_AUTH,
    )

    assert response.status_code == 200
    heartbeat = response.json()["heartbeat"]
    assert heartbeat["phase"] == "debugging"
    assert heartbeat["current_file"] == "server/app.py"
    assert heartbeat["updated_at"]


def test_session_end_finalizes_runtime_to_compact_audit(
    client: testclient.TestClient,
) -> None:
    session_id = _create_trace(client)
    client.post(
        f"/api/traces/{session_id}/runtime/memory",
        json={"kind": "note", "value": {"secret": "sk-ABCDEFabcdef0123456789"}},
        headers=KEY_AUTH,
    )
    client.post(
        f"/api/traces/{session_id}/runtime/tool-call",
        json={"tool_name": "pytest", "status": "failed", "error": "boom"},
        headers=KEY_AUTH,
    )
    client.post(
        f"/api/traces/{session_id}/runtime/heartbeat",
        json={"phase": "debugging"},
        headers=KEY_AUTH,
    )

    response = client.post(
        f"/api/traces/{session_id}/events",
        json={
            "events": [
                _event(session_id, 1, "session_end", {"status": "completed"}),
            ]
        },
        headers=KEY_AUTH,
    )

    assert response.status_code == 200
    audit = client.app.state.store.list_audit(workspace_id="ws_dev")
    runtime_audit = [row for row in audit if row.get("action") == "runtime_finalize"]
    assert runtime_audit
    metadata = runtime_audit[-1]["metadata"]
    assert metadata == {
        "memory_count": 1,
        "tool_fingerprint_count": 1,
        "failed_tool_fingerprint_count": 1,
        "heartbeat_present": True,
    }
    assert "sk-ABCDEF" not in str(metadata)


def test_runtime_off_degrades_safely() -> None:
    client = testclient.TestClient(create_app(runtime_store=NoopRuntimeStore()))
    session_id = _create_trace(client)

    memory = client.post(
        f"/api/traces/{session_id}/runtime/memory",
        json={"kind": "note", "value": {"x": 1}},
        headers=KEY_AUTH,
    )
    tool = client.post(
        f"/api/traces/{session_id}/runtime/tool-call",
        json={"tool_name": "pytest", "status": "failed"},
        headers=KEY_AUTH,
    )
    hint = client.get(f"/api/traces/{session_id}/runtime/hint", headers=KEY_AUTH)

    assert memory.status_code == 200
    assert memory.json() == {"memory": {}}
    assert tool.status_code == 200
    assert tool.json()["seen_recently"] is False
    assert hint.status_code == 200
    assert hint.json() == {"hint": None}


def test_runtime_env_off_and_missing_redis_degrade_safely(monkeypatch) -> None:
    monkeypatch.setenv("PROMPTETHEUS_RUNTIME", "off")

    assert isinstance(runtime_from_env(), NoopRuntimeStore)

    real_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis":
            raise ImportError("redis missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setenv("PROMPTETHEUS_RUNTIME", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("PROMPTETHEUS_REDIS_URL", raising=False)
    monkeypatch.setattr(builtins, "__import__", blocked_import)

    assert isinstance(runtime_from_env(), InMemoryRuntimeStore)
