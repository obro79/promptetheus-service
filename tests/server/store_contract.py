"""Shared Store contract scenarios for InMemoryStore and PostgresStore."""

from __future__ import annotations

from typing import Any

from promptetheus.server.store import Store


def exercise_store_contract(store: Store) -> None:
    session = store.create_session(
        {
            "id": "contract_sess_1",
            "workspace_id": "ws_a",
            "project_id": "proj_a",
            "user_goal": "book meeting",
            "agent": "browser-agent",
            "status": "running",
        }
    )
    assert session["id"] == "contract_sess_1"

    event = {
        "type": "agent_message",
        "session_id": "contract_sess_1",
        "timestamp": "2026-01-01T00:00:00Z",
        "seq": 0,
        "idempotency_key": "contract_sess_1:nonce:0",
        "payload": {"text": "hello"},
    }
    accepted = store.append_event("contract_sess_1", event)
    assert accepted.status == "accepted"
    duplicate = store.append_event("contract_sess_1", event)
    assert duplicate.status == "duplicate"

    conflict = store.append_event(
        "contract_sess_1",
        {
            **event,
            "seq": 0,
            "idempotency_key": "contract_sess_1:nonce:conflict",
        },
    )
    assert conflict.status == "conflict"

    events = store.get_events("contract_sess_1")
    assert len(events) == 1
    assert events[0]["seq"] == 0

    store.set_analysis(
        "contract_sess_1",
        {
            "labels": ["browser_goal_mismatch"],
            "critical_step_seq": 0,
            "confidence": 0.9,
            "root_cause": "wrong time",
            "detections": [],
            "fallback": False,
        },
    )
    sessions = store.list_sessions(workspace_id="ws_a")
    assert any(row["id"] == "contract_sess_1" for row in sessions)
    listed = next(row for row in sessions if row["id"] == "contract_sess_1")
    assert listed["labels"] == ["browser_goal_mismatch"]

    artifact = store.add_artifact(
        {
            "artifact_id": "art_1",
            "workspace_id": "ws_a",
            "session_id": "contract_sess_1",
            "storage_path": "artifacts/ws_a/contract_sess_1/art_1/video.webm",
            "content_type": "video/webm",
            "size_bytes": 42,
            "event_time_map": {"0": 100},
        }
    )
    assert artifact["artifact_id"] == "art_1"
    assert store.get_artifact("art_1") is not None

    incident = store.upsert_incident(
        {
            "id": "inc_1",
            "workspace_id": "ws_a",
            "project_id": "proj_a",
            "label": "browser_goal_mismatch",
            "status": "open",
            "representative_session_id": "contract_sess_1",
            "session_ids": ["contract_sess_1"],
        }
    )
    assert incident["id"] == "inc_1"
    assert store.get_incident("inc_1") is not None
    assert len(store.list_incidents(workspace_id="ws_a")) >= 1

    run = store.add_regression_run(
        {
            "id": "reg_1",
            "workspace_id": "ws_a",
            "project_id": "proj_a",
            "incident_id": "inc_1",
            "before_pass": 0,
            "before_fail": 1,
            "after_pass": 1,
            "after_fail": 0,
            "fallback": True,
        }
    )
    assert run["id"] == "reg_1"
    assert len(store.list_regression_runs("inc_1")) == 1

    audit = store.add_audit(
        {
            "workspace_id": "ws_a",
            "project_id": "proj_a",
            "action": "analyze",
            "incident_id": "inc_1",
            "actor_kind": "server",
            "metadata": {"session_id": "contract_sess_1"},
        }
    )
    assert audit.get("id")
    assert len(store.list_audit(workspace_id="ws_a")) >= 1


def assert_workspace_isolation(store: Store, other_workspace_id: str) -> None:
    sessions = store.list_sessions(workspace_id=other_workspace_id)
    assert all(row.get("workspace_id") == other_workspace_id for row in sessions)
    incidents = store.list_incidents(workspace_id=other_workspace_id)
    assert all(row.get("workspace_id") == other_workspace_id for row in incidents)
