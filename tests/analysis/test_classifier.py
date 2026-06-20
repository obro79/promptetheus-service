"""No-op LLM classifier must not change detector output."""

from __future__ import annotations

from promptetheus.server.analysis.classifier import NoOpClassifier, resolve_classifier
from promptetheus.server.analysis.engine import analyze_session
from promptetheus.server.models import Detection


def _failing_events() -> list[dict]:
    return [
        {
            "type": "user_message",
            "session_id": "s1",
            "timestamp": "2026-01-01T00:00:00Z",
            "seq": 1,
            "idempotency_key": "s1:n:1",
            "payload": {"content": "Book Tuesday"},
        },
        {
            "type": "browser_action",
            "session_id": "s1",
            "timestamp": "2026-01-01T00:00:01Z",
            "seq": 2,
            "idempotency_key": "s1:n:2",
            "payload": {"action": "click", "target": "#wednesday"},
        },
        {
            "type": "dom_snapshot",
            "session_id": "s1",
            "timestamp": "2026-01-01T00:00:02Z",
            "seq": 3,
            "idempotency_key": "s1:n:3",
            "payload": {"selected_values": {"day": "Wednesday"}},
        },
        {
            "type": "browser_action",
            "session_id": "s1",
            "timestamp": "2026-01-01T00:00:03Z",
            "seq": 4,
            "idempotency_key": "s1:n:4",
            "payload": {"action": "click", "target": "#confirm"},
        },
        {
            "type": "agent_message",
            "session_id": "s1",
            "timestamp": "2026-01-01T00:00:04Z",
            "seq": 5,
            "idempotency_key": "s1:n:5",
            "payload": {"content": "Booked!"},
        },
        {
            "type": "goal_check",
            "session_id": "s1",
            "timestamp": "2026-01-01T00:00:05Z",
            "seq": 6,
            "idempotency_key": "s1:n:6",
            "payload": {"passed": False, "mismatches": ["wrong day"]},
        },
    ]


def test_noop_classifier_preserves_root_cause() -> None:
    detections = [
        Detection(
            label="browser_goal_mismatch",
            confidence=0.9,
            evidence_refs=[4],
            critical_step_seq=4,
        )
    ]
    classifier = NoOpClassifier()
    assert classifier.classify(
        user_goal="Tuesday",
        detections=detections,
        root_cause="Agent picked Wednesday.",
    ) == "Agent picked Wednesday."


def test_analyze_session_labels_unchanged_by_classifier(monkeypatch) -> None:
    monkeypatch.setenv("PROMPTETHEUS_ANALYSIS_LLM", "1")
    monkeypatch.setenv("PROMPTETHEUS_ANALYSIS_FALLBACK", "0")
    session = {"id": "s1", "user_goal": "Book Tuesday"}
    result = analyze_session(session, _failing_events())
    assert "browser_goal_mismatch" in result.labels
    assert result.confidence > 0
    assert result.critical_step_seq is not None
    assert resolve_classifier().__class__ is NoOpClassifier
