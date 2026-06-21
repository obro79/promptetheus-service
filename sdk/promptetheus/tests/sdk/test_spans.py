from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.session import Session  # noqa: E402


class RecordingTransport:
    def __init__(self):
        self.events = []
        self.flushed = False

    def send_event(self, event):
        self.events.append(event)

    def flush(self, timeout=None):
        self.flushed = True


def _by_type(events, type_):
    return [e for e in events if e["type"] == type_]


def test_events_are_flat_without_a_span():
    transport = RecordingTransport()
    session = Session(agent="a", user_goal="g", session_id="s1", transport=transport)
    session.agent_message("hello")
    session.tool_call("t")
    for event in transport.events:
        assert "span_id" not in event
        assert "parent_id" not in event


def test_span_stamps_span_id_and_parent_id_none_at_top_level():
    transport = RecordingTransport()
    session = Session(agent="a", user_goal="g", session_id="s1", transport=transport)

    with session.span("outer") as span_id:
        session.agent_message("inside")

    msg = _by_type(transport.events, "agent_message")[0]
    assert msg["span_id"] == span_id
    assert msg["parent_id"] is None

    starts = [e for e in transport.events if e["payload"].get("name") == "span_start"]
    ends = [e for e in transport.events if e["payload"].get("name") == "span_end"]
    assert len(starts) == 1 and len(ends) == 1
    assert starts[0]["payload"]["span_name"] == "outer"
    assert starts[0]["span_id"] == span_id


def test_nested_spans_build_a_tree():
    transport = RecordingTransport()
    session = Session(agent="a", user_goal="g", session_id="s1", transport=transport)

    with session.span("outer") as outer_id:
        session.agent_message("in-outer")
        with session.span("inner") as inner_id:
            session.agent_message("in-inner")
        session.agent_message("back-in-outer")

    assert outer_id != inner_id

    outer_msgs = [
        e for e in _by_type(transport.events, "agent_message")
        if e["span_id"] == outer_id
    ]
    inner_msgs = [
        e for e in _by_type(transport.events, "agent_message")
        if e["span_id"] == inner_id
    ]

    assert {e["payload"]["content"] for e in outer_msgs} == {"in-outer", "back-in-outer"}
    assert all(e["parent_id"] is None for e in outer_msgs)

    assert {e["payload"]["content"] for e in inner_msgs} == {"in-inner"}
    assert all(e["parent_id"] == outer_id for e in inner_msgs)


def test_events_after_span_exit_are_flat_again():
    transport = RecordingTransport()
    session = Session(agent="a", user_goal="g", session_id="s1", transport=transport)

    with session.span("outer"):
        session.agent_message("inside")
    session.agent_message("after")

    after = [e for e in _by_type(transport.events, "agent_message") if e["payload"]["content"] == "after"][0]
    assert "span_id" not in after
    assert "parent_id" not in after


def test_three_level_tree_parent_chain():
    transport = RecordingTransport()
    session = Session(agent="a", user_goal="g", session_id="s1", transport=transport)

    with session.span("l1") as l1:
        with session.span("l2") as l2:
            with session.span("l3") as l3:
                session.agent_message("deep")

    deep = [e for e in _by_type(transport.events, "agent_message")][0]
    assert deep["span_id"] == l3
    assert deep["parent_id"] == l2

    l3_start = [
        e for e in transport.events
        if e["payload"].get("name") == "span_start" and e["payload"].get("span_name") == "l3"
    ][0]
    assert l3_start["span_id"] == l3
    assert l3_start["parent_id"] == l2

    l2_start = [
        e for e in transport.events
        if e["payload"].get("name") == "span_start" and e["payload"].get("span_name") == "l2"
    ][0]
    assert l2_start["parent_id"] == l1
