"""Tests for the event-driven auto-heal trigger.

The trigger must be OFF by default, recognize failure-signaling events, and —
when enabled — analyze a session, assemble incidents, and run the heal loop for
each. The heavy path runs synchronously via run_auto_heal here so it is
deterministic (the request path schedules it on a daemon thread).
"""

from __future__ import annotations

import pytest

from promptetheus.server.fix_agent import triggers
from promptetheus.server.store import InMemoryStore


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("PROMPTETHEUS_AUTO_HEAL", raising=False)


def test_is_failure_event_classifies_event_types() -> None:
    assert triggers.is_failure_event({"type": "error", "payload": {}})
    assert triggers.is_failure_event({"type": "goal_check", "payload": {"passed": False}})
    assert triggers.is_failure_event(
        {"type": "tool_result", "payload": {"status": "failed"}}
    )
    assert triggers.is_failure_event(
        {"type": "session_end", "payload": {"status": "crashed"}}
    )
    # Non-failures.
    assert not triggers.is_failure_event({"type": "goal_check", "payload": {"passed": True}})
    assert not triggers.is_failure_event({"type": "agent_message", "payload": {}})
    assert not triggers.is_failure_event({"type": "session_end", "payload": {"status": "completed"}})


def test_disabled_by_default_does_not_schedule() -> None:
    store = InMemoryStore()
    scheduled = triggers.maybe_trigger_auto_heal(
        store, "sess_1", [{"type": "error", "payload": {}}]
    )
    assert scheduled is False


def test_enabled_only_schedules_on_failure_event(monkeypatch) -> None:
    monkeypatch.setenv("PROMPTETHEUS_AUTO_HEAL", "1")
    calls: list[str] = []
    monkeypatch.setattr(triggers, "run_auto_heal", lambda store, sid: calls.append(sid))

    store = InMemoryStore()
    # No failure event -> not scheduled.
    assert not triggers.maybe_trigger_auto_heal(
        store, "sess_1", [{"type": "agent_message", "payload": {}}]
    )
    # A failure event -> scheduled (background thread invokes run_auto_heal).
    assert triggers.maybe_trigger_auto_heal(
        store, "sess_1", [{"type": "goal_check", "payload": {"passed": False}}]
    )


def _seed_failing_session(store: InMemoryStore) -> None:
    store.create_session(
        {
            "id": "sess_1",
            "workspace_id": "ws_dev",
            "project_id": "proj_dev",
            "user_goal": "Book a 30 minute AcmeMeet with Dana on Tuesday at 2pm",
            "source": "browserbase",
        }
    )
    store.append_event(
        "sess_1",
        {
            "type": "goal_check",
            "session_id": "sess_1",
            "timestamp": "2026-06-12T09:00:05+00:00",
            "seq": 5,
            "idempotency_key": "sess_1-5",
            "payload": {"passed": False, "mismatches": ["wrong slot selected"]},
        },
    )


def test_run_auto_heal_analyzes_and_heals(monkeypatch) -> None:
    store = InMemoryStore()
    _seed_failing_session(store)

    summary = triggers.run_auto_heal(store, "sess_1")

    # An incident was assembled and the heal loop ran + audited.
    assert summary["incidents"], summary
    assert summary["healed"] >= 1
    analysis = store.get_analysis("sess_1")
    assert analysis is not None and analysis["labels"]
    actions = [a["action"] for a in store.list_audit(workspace_id="ws_dev")]
    assert "auto_heal_trigger" in actions


def test_run_auto_heal_missing_session_is_noop() -> None:
    store = InMemoryStore()
    summary = triggers.run_auto_heal(store, "nope")
    assert summary == {"session_id": "nope", "incidents": [], "healed": 0}
