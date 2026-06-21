"""Failure fingerprinting: stability, collapsing, and clean-session behavior."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.fingerprint import failure_fingerprint  # noqa: E402


def _ev(etype, payload=None):
    return {"type": etype, "payload": payload or {}}


def _failed(message):
    return [_ev("error", {"message": message}), _ev("session_end", {"status": "failed"})]


def test_clean_session_has_no_fingerprint():
    events = [_ev("agent_message", {"content": "hi"}), _ev("goal_check", {"passed": True}),
              _ev("session_end", {"status": "completed"})]
    fp = failure_fingerprint(events)
    assert fp.is_failure is False
    assert fp.fingerprint == ""


def test_same_error_class_collapses_despite_varying_numbers():
    a = failure_fingerprint(_failed("TimeoutError: timed out after 3133ms"))
    b = failure_fingerprint(_failed("TimeoutError: timed out after 9120ms"))
    assert a.is_failure and b.is_failure
    assert a.fingerprint == b.fingerprint  # numbers normalized away


def test_different_error_classes_differ():
    a = failure_fingerprint(_failed("TimeoutError: timed out"))
    b = failure_fingerprint(_failed("ValueError: bad input"))
    assert a.fingerprint != b.fingerprint


def test_fingerprint_is_order_independent_within_session():
    e1 = _ev("error", {"message": "ValueError: x"})
    e2 = _ev("goal_check", {"passed": False, "mismatches": ["wrong answer"]})
    end = _ev("session_end", {"status": "failed"})
    a = failure_fingerprint([e1, e2, end])
    b = failure_fingerprint([e2, e1, end])
    assert a.fingerprint == b.fingerprint


def test_failed_tool_result_contributes():
    events = [_ev("tool_call", {"tool": "search"}),
              _ev("tool_result", {"tool": "search", "error": "503 upstream"}),
              _ev("session_end", {"status": "failed"})]
    fp = failure_fingerprint(events)
    assert fp.is_failure
    assert any("tool_error:search" in s for s in fp.signals)


def test_goal_mismatch_fingerprints():
    events = [_ev("goal_check", {"passed": False, "mismatches": ["expected 5 got 7"]}),
              _ev("session_end", {"status": "completed"})]
    fp = failure_fingerprint(events)
    assert fp.is_failure
    assert "goal mismatch" in fp.label


def test_label_summarizes_multiple_signals():
    events = _failed("ValueError: bad") + [_ev("goal_check", {"passed": False})]
    fp = failure_fingerprint(events)
    assert "more" in fp.label  # leads with one signal, notes the rest


def test_never_raises_on_malformed():
    fp = failure_fingerprint([{"no": "type"}, None, 7, _ev("error", {"message": None})])  # type: ignore[list-item]
    assert fp.is_failure  # the lone error still registers


def test_quoted_and_path_literals_normalized():
    a = failure_fingerprint(_failed("FileNotFoundError: '/home/alice/x.txt' missing"))
    b = failure_fingerprint(_failed("FileNotFoundError: '/home/bob/y.txt' missing"))
    assert a.fingerprint == b.fingerprint
