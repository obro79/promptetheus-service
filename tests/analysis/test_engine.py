"""Engine contract tests: aggregation + incident clustering.

Covers analyze_session aggregation (min critical step, max confidence,
root_cause present when something fires; empty result otherwise) and
assemble_incidents clustering (deterministic id, severity, deduped
session_ids, status "new", preserved status/representative on re-upsert).

Built against the real engine + the real InMemoryStore. Events are plain
envelope dicts.

Tests run from the repo root: packages/promptetheus is put on sys.path the
same way tests/schema does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server.analysis.engine import (  # noqa: E402
    analyze_session,
    assemble_incidents,
)
from promptetheus.server.store import InMemoryStore  # noqa: E402


SESSION_ID = "sess_engine"
WORKSPACE_ID = "ws_dev"
PROJECT_ID = "proj_dev"


def _event(event_type: str, seq: int, payload: dict, metadata: dict | None = None) -> dict:
    event: dict = {
        "type": event_type,
        "session_id": SESSION_ID,
        "timestamp": "2026-06-12T12:00:00.000Z",
        "seq": seq,
        "idempotency_key": f"{SESSION_ID}:nonce:{seq}",
        "payload": payload,
    }
    if metadata is not None:
        event["metadata"] = metadata
    return event


def _failing_session_events() -> list[dict]:
    """A session that fires browser_goal_mismatch (0.9), ignored_ui_warning,
    and false_success_claim — a realistic multi-label failure."""

    return [
        _event("user_message", 1, {"content": "Book a Monday slot but stop at confirmation"}),
        _event("browser_action", 2, {"action": "fill", "target": "day", "value": "Tuesday"}),
        _event("dom_snapshot", 3, {"warnings": ["No seats remaining"], "visible_text": "pick"}),
        _event("browser_action", 4, {"action": "click", "target": "continue"}),
        _event(
            "dom_snapshot",
            5,
            {"selected_values": {"day": "Tuesday"}, "warnings": ["No seats remaining"]},
        ),
        _event("browser_action", 6, {"action": "submit", "target": "confirm"}),
        _event("goal_check", 7, {"passed": False, "mismatches": ["day should be Monday"]}),
        _event("agent_message", 8, {"content": "All booked! You're confirmed."}),
        _event("session_end", 9, {"status": "success"}),
    ]


def _session_row() -> dict:
    return {
        "id": SESSION_ID,
        "workspace_id": WORKSPACE_ID,
        "project_id": PROJECT_ID,
        "user_goal": "Book a Monday slot but stop at confirmation",
    }


# ===========================================================================
# analyze_session aggregation
# ===========================================================================


def test_analyze_session_aggregates_min_critical_max_confidence_and_root_cause() -> None:
    result = analyze_session(_session_row(), _failing_session_events())

    assert result.session_id == SESSION_ID
    assert result.detections, "expected at least one detection to fire"

    # Aggregation invariants (INTERNAL_CONTRACT section 2).
    expected_confidence = max(d.confidence for d in result.detections)
    assert result.confidence == expected_confidence

    crit_steps = [d.critical_step_seq for d in result.detections if d.critical_step_seq is not None]
    assert result.critical_step_seq == min(crit_steps)

    assert result.root_cause is not None
    assert result.root_cause != ""

    # A strong goal mismatch -> confidence reaches 0.9+ and that label is present.
    assert "browser_goal_mismatch" in result.labels
    assert result.confidence >= 0.9


def test_analyze_session_back_compat_dict_shape() -> None:
    """as_dict must preserve the locked back-compat fields for the API."""

    result = analyze_session(_session_row(), _failing_session_events())
    row = result.as_dict()

    assert row["trace_id"] == SESSION_ID
    assert row["labels"] == result.labels
    assert row["critical_step_seq"] == result.critical_step_seq
    assert row["confidence"] == result.confidence
    assert "detections" in row
    assert "root_cause" in row


def test_analyze_session_empty_when_nothing_fires() -> None:
    """A clean run fires nothing: empty detections, 0.0 confidence, no root cause."""

    events = [
        _event("user_message", 1, {"content": "Book Monday"}),
        _event("browser_action", 2, {"action": "fill", "target": "day", "value": "Monday"}),
        _event("dom_snapshot", 3, {"selected_values": {"day": "Monday"}, "warnings": []}),
        _event("goal_check", 4, {"passed": True}),
        _event("agent_message", 5, {"content": "All set for Monday."}),
    ]
    session = {**_session_row(), "user_goal": "Book Monday"}

    result = analyze_session(session, events)

    assert result.detections == []
    assert result.confidence == 0.0
    assert result.critical_step_seq is None
    assert result.root_cause is None


# ===========================================================================
# assemble_incidents clustering
# ===========================================================================


def test_assemble_incidents_deterministic_id_severity_status_and_dedup() -> None:
    store = InMemoryStore()
    session = _session_row()
    result = analyze_session(session, _failing_session_events())

    incidents = assemble_incidents(store, session, result)

    assert incidents, "expected incidents to be created"

    by_label = {row["label"]: row for row in incidents}

    for label, row in by_label.items():
        # Deterministic identity per (workspace, label).
        assert row["id"] == f"incident_{WORKSPACE_ID}_{label}"
        assert row["workspace_id"] == WORKSPACE_ID
        assert row["project_id"] == PROJECT_ID
        # First creation -> status "new".
        assert row["status"] == "new"
        assert row["representative_session_id"] == SESSION_ID
        assert row["owner_id"] is None
        # session_ids deduped, contains this session once.
        assert row["session_ids"].count(SESSION_ID) == 1
        # Severity keys off confidence threshold.
        expected = "high" if row["confidence"] >= 0.9 else "medium"
        assert row["severity"] == expected

    # The high-confidence goal mismatch yields a "high" severity incident.
    assert by_label["browser_goal_mismatch"]["severity"] == "high"


def test_assemble_incidents_dedups_session_across_reanalysis() -> None:
    """Re-running the same session must not duplicate its session_id, and the
    "new" status / representative session are preserved across upsert."""

    store = InMemoryStore()
    session = _session_row()
    result = analyze_session(session, _failing_session_events())

    first = assemble_incidents(store, session, result)
    # Simulate a later triage before re-analysis.
    mismatch_id = f"incident_{WORKSPACE_ID}_browser_goal_mismatch"
    store.update_incident(mismatch_id, {"status": "triaged", "owner_id": "user_1"})

    second = assemble_incidents(store, session, result)

    second_by_label = {row["label"]: row for row in second}
    mismatch = second_by_label["browser_goal_mismatch"]

    # No duplicate session id after re-analysis.
    assert mismatch["session_ids"] == [SESSION_ID]
    # Existing status + owner preserved (not reset to "new"/None).
    assert mismatch["status"] == "triaged"
    assert mismatch["owner_id"] == "user_1"
    # Same deterministic id across runs.
    assert {r["id"] for r in first} == {r["id"] for r in second}


def test_assemble_incidents_clusters_two_sessions_into_one_incident() -> None:
    """Two distinct sessions firing the same label land in ONE incident with both
    session ids; severity reflects the max confidence seen."""

    store = InMemoryStore()

    session_a = _session_row()
    result_a = analyze_session(session_a, _failing_session_events())
    assemble_incidents(store, session_a, result_a)

    # A second session with a different id but the same failing shape.
    session_b = {**_session_row(), "id": "sess_engine_b"}
    events_b = [dict(e, session_id="sess_engine_b") for e in _failing_session_events()]
    result_b = analyze_session(session_b, events_b)
    incidents_b = assemble_incidents(store, session_b, result_b)

    mismatch = {row["label"]: row for row in incidents_b}["browser_goal_mismatch"]

    assert set(mismatch["session_ids"]) == {SESSION_ID, "sess_engine_b"}
    assert mismatch["id"] == f"incident_{WORKSPACE_ID}_browser_goal_mismatch"


def test_assemble_incidents_empty_when_no_detections() -> None:
    store = InMemoryStore()
    session = {**_session_row(), "user_goal": "Book Monday"}
    events = [
        _event("user_message", 1, {"content": "Book Monday"}),
        _event("browser_action", 2, {"action": "fill", "target": "day", "value": "Monday"}),
        _event("dom_snapshot", 3, {"selected_values": {"day": "Monday"}, "warnings": []}),
        _event("goal_check", 4, {"passed": True}),
    ]
    result = analyze_session(session, events)

    incidents = assemble_incidents(store, session, result)

    assert incidents == []
    assert store.list_incidents(workspace_id=WORKSPACE_ID) == []
