from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

import promptetheus as pt  # noqa: E402
from promptetheus.session import Session, _should_record  # noqa: E402


class RecordingTransport:
    def __init__(self):
        self.events = []
        self.batches = []
        self.traces = []
        self.flushed = False

    def create_trace(self, trace):
        self.traces.append(trace)

    def send_event(self, event):
        self.events.append(event)

    def send_batch(self, events):
        events = list(events)
        self.batches.append(events)
        self.events.extend(events)

    def flush(self, timeout=None):
        self.flushed = True


def _find_dropped_session_id(sample_rate: float) -> str:
    # A session id that the head sample_rate would drop (boring success path).
    for i in range(10000):
        sid = f"sess_drop_{i}"
        if not _should_record(sid, sample_rate):
            return sid
    raise AssertionError("could not find a droppable session id")


def _find_kept_session_id(sample_rate: float) -> str:
    for i in range(10000):
        sid = f"sess_keep_{i}"
        if _should_record(sid, sample_rate):
            return sid
    raise AssertionError("could not find a keepable session id")


def test_tail_sample_buffers_until_end():
    transport = RecordingTransport()
    session = Session(
        agent="a", user_goal="g", session_id="s1", transport=transport, tail_sample=True
    )
    with session:
        session.agent_message("hello")
        # Nothing sent yet: tail sampling buffers in memory.
        assert transport.events == []
        assert transport.traces == []
    # Completed + sample_rate 1.0 default keeps it: whole timeline flushed.
    assert [e["type"] for e in transport.events][0] == "state_change"
    assert transport.events[-1]["type"] == "session_end"


def test_failing_session_is_kept_in_full_even_when_head_would_drop():
    sample_rate = 0.5
    sid = _find_dropped_session_id(sample_rate)
    transport = RecordingTransport()
    session = Session(
        agent="a",
        user_goal="g",
        session_id=sid,
        transport=transport,
        sample_rate=sample_rate,
        tail_sample=True,
    )
    with session:
        session.agent_message("step 1")
        session.tool_call("do_thing")
        session.goal_check(False, mismatches=["wrong result"])

    # Interesting (failed goal_check) forces a full flush despite head drop.
    types = [e["type"] for e in transport.events]
    assert "agent_message" in types
    assert "tool_call" in types
    assert "goal_check" in types
    assert types[-1] == "session_end"
    # Trace record was created on the keep decision.
    assert len(transport.traces) == 1


def test_exception_forces_keep():
    sample_rate = 0.5
    sid = _find_dropped_session_id(sample_rate)
    transport = RecordingTransport()
    try:
        with Session(
            agent="a",
            user_goal="g",
            session_id=sid,
            transport=transport,
            sample_rate=sample_rate,
            tail_sample=True,
        ) as session:
            session.agent_message("before boom")
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    types = [e["type"] for e in transport.events]
    assert "agent_message" in types
    end = [e for e in transport.events if e["type"] == "session_end"][0]
    assert end["payload"]["status"] == "failed"
    assert "boom" in (end["payload"]["error"] or "")


def test_session_end_error_forces_keep():
    sample_rate = 0.5
    sid = _find_dropped_session_id(sample_rate)
    transport = RecordingTransport()
    session = Session(
        agent="a",
        user_goal="g",
        session_id=sid,
        transport=transport,
        sample_rate=sample_rate,
        tail_sample=True,
    )
    with session:
        session.agent_message("step")
        session.end("completed", error="explicit failure signal")

    assert any(e["type"] == "agent_message" for e in transport.events)
    assert transport.traces


def test_boring_success_is_dropped_when_head_sample_drops():
    sample_rate = 0.5
    sid = _find_dropped_session_id(sample_rate)
    transport = RecordingTransport()
    session = Session(
        agent="a",
        user_goal="g",
        session_id=sid,
        transport=transport,
        sample_rate=sample_rate,
        tail_sample=True,
    )
    with session:
        session.agent_message("uneventful")
        session.goal_check(True)

    # Boring success + head sample drop => whole session dropped (all-or-nothing).
    assert transport.events == []
    assert transport.traces == []


def test_boring_success_kept_when_head_sample_keeps():
    sample_rate = 0.5
    sid = _find_kept_session_id(sample_rate)
    transport = RecordingTransport()
    session = Session(
        agent="a",
        user_goal="g",
        session_id=sid,
        transport=transport,
        sample_rate=sample_rate,
        tail_sample=True,
    )
    with session:
        session.agent_message("uneventful")
        session.goal_check(True)

    assert any(e["type"] == "agent_message" for e in transport.events)
    assert transport.traces


def test_default_tail_sample_is_immediate_send():
    transport = RecordingTransport()
    session = Session(agent="a", user_goal="g", session_id="s1", transport=transport)
    with session:
        session.agent_message("hello")
        # Immediate mode: event already delivered before end().
        assert any(e["type"] == "agent_message" for e in transport.events)


def test_observe_threads_tail_sample():
    transport = RecordingTransport()

    @pt.observe(agent="x", user_goal="g", transport=transport, tail_sample=True)
    def run():
        pt.current().agent_message("inside")
        return 7

    assert run() == 7
    types = [e["type"] for e in transport.events]
    assert "agent_message" in types
    assert types[-1] == "session_end"
