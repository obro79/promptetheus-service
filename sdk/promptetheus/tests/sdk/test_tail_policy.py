"""Tail-sampling policy: keep signals, boring-success keep-rate, drop skeleton."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

import promptetheus as pt  # noqa: E402
from promptetheus.sampling import TailSamplingPolicy  # noqa: E402
from promptetheus.session import Session, _should_record  # noqa: E402


class Rec:
    def __init__(self):
        self.events = []
        self.traces = []

    def create_trace(self, trace):
        self.traces.append(trace)

    def send_event(self, event):
        self.events.append(event)

    def send_batch(self, events):
        self.events.extend(dict(e) for e in events)

    def flush(self, timeout=None):
        pass


def _evt(etype, payload=None, key="k"):
    return {"type": etype, "idempotency_key": key, "payload": payload or {}}


def _span_end(name, duration_ms):
    return _evt(
        "state_change",
        {"name": "span_end", "span_name": name, "duration_ms": duration_ms},
    )


# -- pure policy ------------------------------------------------------------


def test_error_event_is_interesting():
    p = TailSamplingPolicy()
    keep, reason = p.interesting([_evt("agent_message"), _evt("error", {"message": "boom"})])
    assert keep and reason == "error event"


def test_failed_goal_check_is_interesting():
    p = TailSamplingPolicy()
    keep, reason = p.interesting([_evt("goal_check", {"passed": False})])
    assert keep and reason == "failed goal_check"


def test_retry_loop_is_interesting():
    p = TailSamplingPolicy(retry_loop_threshold=3)
    same = _evt("tool_call", {"tool": "search", "arguments": {"q": "x"}})
    keep, reason = p.interesting([dict(same) for _ in range(3)])
    assert keep and reason.startswith("retry loop on search")
    # Two repeats is below the threshold -> not interesting on that signal alone.
    keep2, _ = p.interesting([dict(same) for _ in range(2)])
    assert keep2 is False


def test_latency_outlier_single_span_is_interesting():
    p = TailSamplingPolicy(span_latency_ms_threshold=1000.0)
    keep, reason = p.interesting([_span_end("slow", 5000)])
    assert keep and reason.startswith("slow span slow")


def test_session_latency_sum_is_interesting():
    p = TailSamplingPolicy(span_latency_ms_threshold=10_000.0, session_latency_ms_threshold=1500.0)
    events = [_span_end("s", 800) for _ in range(3)]
    keep, reason = p.interesting(events)
    assert keep and reason.startswith("slow session")


def test_boring_success_not_interesting():
    p = TailSamplingPolicy()
    keep, reason = p.interesting([_evt("agent_message"), _evt("goal_check", {"passed": True})])
    assert keep is False and reason == "boring success"


def test_policy_never_raises_on_malformed():
    p = TailSamplingPolicy()
    keep, _ = p.interesting([{"no": "type"}, None, 42, _evt("span_end", {"duration_ms": "nan"})])  # type: ignore[list-item]
    assert keep is False


def test_decide_defers_to_head_rate_for_boring():
    p = TailSamplingPolicy()  # boring_success_keep_rate=None -> use head rate
    boring = [_evt("goal_check", {"passed": True})]
    # head 1.0 keeps, head 0.0 drops
    assert p.decide(boring, session_id="s", head_sample_rate=1.0).keep is True
    assert p.decide(boring, session_id="s", head_sample_rate=0.0).keep is False


def test_decide_explicit_boring_rate_overrides_head():
    p = TailSamplingPolicy(boring_success_keep_rate=0.0)
    boring = [_evt("goal_check", {"passed": True})]
    # even with head 1.0, an explicit 0.0 boring rate drops the boring success
    assert p.decide(boring, session_id="s", head_sample_rate=1.0).keep is False


# -- wired into Session -----------------------------------------------------


def test_session_custom_policy_drops_boring_success():
    t = Rec()
    policy = TailSamplingPolicy(boring_success_keep_rate=0.0)
    with Session(agent="a", user_goal="g", session_id="s1", transport=t, tail_sample=True, tail_policy=policy):
        pt.current()  # boring, successful
    assert t.events == []  # dropped by the 0.0 boring keep-rate


def test_session_retry_loop_keeps_via_policy():
    t = Rec()
    policy = TailSamplingPolicy(retry_loop_threshold=2, boring_success_keep_rate=0.0)
    with Session(agent="a", user_goal="g", session_id="s2", transport=t, tail_sample=True, tail_policy=policy) as s:
        s.tool_call("search", arguments={"q": "x"})
        s.tool_call("search", arguments={"q": "x"})
    types = [e["type"] for e in t.events]
    assert "tool_call" in types and types[-1] == "session_end"  # kept despite boring rate 0


def test_drop_skeleton_emits_minimal_record():
    t = Rec()
    policy = TailSamplingPolicy(boring_success_keep_rate=0.0, emit_skeleton_on_drop=True)
    with Session(agent="a", user_goal="g", session_id="s3", transport=t, tail_sample=True, tail_policy=policy) as s:
        s.agent_message("uneventful")
        s.agent_message("still boring")
    # Skeleton: the opening event + an annotated session_end (the two agent_messages elided).
    types = [e["type"] for e in t.events]
    assert "agent_message" not in types
    end = [e for e in t.events if e["type"] == "session_end"][0]
    assert end["payload"]["tail_dropped"] is True
    assert end["payload"]["tail_dropped_event_count"] >= 3
    assert "boring success" in end["payload"]["tail_drop_reason"]


def test_default_policy_preserves_head_rate_behavior():
    # A plain tail_sample=True with no custom policy keeps a boring success when
    # the head sample_rate keeps it (unchanged from before the policy existed).
    for i in range(10000):
        sid = f"keep_{i}"
        if _should_record(sid, 0.5):
            break
    t = Rec()
    with Session(agent="a", user_goal="g", session_id=sid, transport=t, tail_sample=True, sample_rate=0.5):
        pt.current()
    assert any(e["type"] == "session_end" for e in t.events)
