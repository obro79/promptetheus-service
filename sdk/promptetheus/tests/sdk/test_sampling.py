from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

import promptetheus as pt  # noqa: E402
from promptetheus.session import Session, _should_record  # noqa: E402


class RecordingTransport:
    def __init__(self):
        self.events = []
        self.flushed = False

    def send_event(self, event):
        self.events.append(event)

    def flush(self, timeout=None):
        self.flushed = True


def test_should_record_extremes():
    assert _should_record("any", 1.0) is True
    assert _should_record("any", 0.0) is False


def test_should_record_is_deterministic_per_session():
    assert _should_record("sess_abc", 0.5) == _should_record("sess_abc", 0.5)
    assert _should_record("sess_xyz", 0.5) == _should_record("sess_xyz", 0.5)


def test_sampled_out_session_emits_nothing_but_runs():
    transport = RecordingTransport()
    session = Session(
        agent="a", user_goal="g", session_id="s1", transport=transport, sample_rate=0.0
    )
    session.agent_message("hello")
    session.tool_call("t")
    assert transport.events == []


def test_sampled_in_session_emits():
    transport = RecordingTransport()
    session = Session(
        agent="a", user_goal="g", session_id="s1", transport=transport, sample_rate=1.0
    )
    session.agent_message("hello")
    assert [e["type"] for e in transport.events] == ["agent_message"]


def test_observe_respects_sample_rate_zero():
    transport = RecordingTransport()

    @pt.observe(agent="x", user_goal="g", transport=transport, sample_rate=0.0)
    def run():
        pt.current().agent_message("inside")
        return 7

    assert run() == 7  # user code still runs
    assert transport.events == []  # but nothing recorded


def test_async_observe_records_when_sampled_in():
    transport = RecordingTransport()

    @pt.observe(agent="x", user_goal="g", transport=transport, sample_rate=1.0)
    async def run():
        pt.current().agent_message("inside")
        return 5

    assert asyncio.run(run()) == 5
    types = [e["type"] for e in transport.events]
    assert types[0] == "state_change"
    assert "agent_message" in types
    assert types[-1] == "session_end"
