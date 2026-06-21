"""First-class score / error / metric events + metadata/tags + the traced span decorator."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

import promptetheus as pt  # noqa: E402
from promptetheus.schema import EVENT_TYPES, validate_event  # noqa: E402
from promptetheus.session import Session  # noqa: E402


class Rec:
    def __init__(self):
        self.events = []

    def send_event(self, event):
        self.events.append(event)

    def flush(self, timeout=None):
        pass


def _session() -> tuple[Session, Rec]:
    t = Rec()
    return Session(agent="a", user_goal="g", session_id="s", transport=t), t


def test_new_event_types_registered_and_valid():
    for name in ("score", "error", "metric"):
        assert name in EVENT_TYPES


def test_score_event():
    s, t = _session()
    ev = s.score("helpfulness", 0.8, comment="good", source="human")
    assert ev["type"] == "score"
    assert ev["payload"] == {"name": "helpfulness", "value": 0.8, "comment": "good", "source": "human"}
    validate_event(ev)


def test_metric_event():
    s, t = _session()
    ev = s.metric("retrieved_docs", 5, unit="count")
    assert ev["type"] == "metric"
    assert ev["payload"] == {"name": "retrieved_docs", "value": 5, "unit": "count"}


def test_error_event_from_exception_captures_traceback():
    s, t = _session()
    try:
        raise ValueError("boom")
    except ValueError as exc:
        ev = s.error(exc)
    assert ev["type"] == "error"
    assert ev["payload"]["message"] == "boom"
    assert ev["payload"]["error_type"] == "ValueError"
    assert "ValueError: boom" in ev["payload"]["traceback"]
    assert ev["payload"]["handled"] is True
    validate_event(ev)


def test_error_event_from_string():
    s, t = _session()
    ev = s.error("something off", error_type="Custom", handled=False)
    assert ev["payload"]["message"] == "something off"
    assert ev["payload"]["error_type"] == "Custom"
    assert ev["payload"]["handled"] is False
    assert "traceback" not in ev["payload"]


def test_update_metadata_and_add_tags():
    s, t = _session()
    s.update_metadata(user_id="u1", plan="pro")
    assert s.metadata["user_id"] == "u1"
    upd = next(e for e in t.events if e["payload"].get("name") == "metadata_update")
    assert upd["payload"]["after"] == {"user_id": "u1", "plan": "pro"}

    s.add_tags("vip", "beta", "vip")  # dedupes
    assert s.tags.count("vip") == 1
    tagev = next(e for e in t.events if e["payload"].get("name") == "tags_added")
    assert tagev["payload"]["after"]["tags"] == ["vip", "beta"]


def test_traced_decorator_opens_a_span():
    t = Rec()

    @pt.observe(agent="x", user_goal="g", transport=t)
    def run():
        @pt.traced("retrieve")
        def retrieve():
            return pt.current().agent_message("inside retrieve")

        return retrieve()

    deep = run()
    starts = [
        e for e in t.events
        if e["type"] == "state_change" and e["payload"].get("name") == "span_start"
    ]
    assert any(s["payload"].get("span_name") == "retrieve" for s in starts)
    # the agent_message inside the decorated fn carries the span id
    assert "span_id" in deep


def test_traced_is_noop_without_session():
    @pt.traced("x")
    def f(a, b):
        return a + b

    assert f(2, 3) == 5  # runs fine with no active session


def test_noop_session_new_helpers_are_safe():
    noop = pt.current()  # no active session -> NoopSession
    assert noop.score("x", 1) is None
    assert noop.metric("y", 2) is None
    assert noop.error("z") is None
