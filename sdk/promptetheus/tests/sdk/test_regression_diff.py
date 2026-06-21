"""Session diffing + golden regression assertions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.regression import (  # noqa: E402
    assert_no_regression,
    diff_sessions,
    extract_steps,
)


def _ev(seq, etype, payload=None):
    return {"type": etype, "seq": seq, "payload": payload or {}}


def _session(*steps):
    out = [_ev(0, "state_change", {"name": "session_start"})]
    for i, (etype, payload) in enumerate(steps, start=1):
        out.append(_ev(i, etype, payload))
    out.append(_ev(len(steps) + 1, "session_end", {"status": "completed"}))
    return out


def test_identical_sessions_have_no_diff():
    a = _session(("tool_call", {"tool": "search"}), ("goal_check", {"passed": True}))
    diff = diff_sessions(a, list(a))
    assert not diff.added and not diff.removed and not diff.changed
    assert diff.regressed is False
    assert diff.summary() == ""


def test_added_and_removed_steps():
    a = _session(("tool_call", {"tool": "search"}))
    b = _session(("tool_call", {"tool": "search"}), ("tool_call", {"tool": "browse"}))
    diff = diff_sessions(a, b)
    assert any("browse" in s.label for s in diff.added)
    assert not diff.removed

    diff2 = diff_sessions(b, a)
    assert any("browse" in s.label for s in diff2.removed)


def test_goal_check_pass_to_fail_is_regression():
    a = _session(("goal_check", {"passed": True}))
    b = _session(("goal_check", {"passed": False}))
    diff = diff_sessions(a, b)
    assert diff.regressed is True
    assert any(c.regressed for c in diff.changed)


def test_fail_to_pass_is_change_not_regression():
    a = _session(("goal_check", {"passed": False}))
    b = _session(("goal_check", {"passed": True}))
    diff = diff_sessions(a, b)
    assert diff.regressed is False
    assert diff.changed  # it is reported as a (positive) change


def test_new_error_is_regression():
    a = _session(("tool_call", {"tool": "search"}))
    b = _session(("tool_call", {"tool": "search"}), ("error", {"message": "boom"}))
    diff = diff_sessions(a, b)
    assert diff.regressed is True


def test_duration_change_reported_not_regression():
    a = _session(("span_end", {"name": "fetch", "duration_ms": 100}))
    b = _session(("span_end", {"name": "fetch", "duration_ms": 5000}))
    diff = diff_sessions(a, b)
    assert diff.regressed is False
    assert any("duration" in c.detail for c in diff.changed)


def test_assert_no_regression_raises_on_regression():
    golden = _session(("goal_check", {"passed": True}))
    candidate = _session(("goal_check", {"passed": False}))
    with pytest.raises(AssertionError):
        assert_no_regression(golden, candidate)


def test_assert_no_regression_silent_when_clean():
    golden = _session(("tool_call", {"tool": "search"}))
    assert_no_regression(golden, list(golden)) is None


def test_diff_never_raises_on_malformed():
    diff = diff_sessions([{"no": "type"}, None, 7], [42, {"type": "error"}])  # type: ignore[list-item]
    assert diff.regressed is True  # the lone error in B counts as a new failure


def test_extract_steps_orders_and_keys():
    events = _session(("tool_call", {"tool": "x"}), ("tool_call", {"tool": "x"}))
    steps = extract_steps(events)
    keys = [s.key for s in steps]
    # repeated identical tool calls stay distinguishable by ordinal
    assert keys.count("tool_call:x#1") == 1 and keys.count("tool_call:x#2") == 1
