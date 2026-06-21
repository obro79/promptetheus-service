"""Cross-feature integration tests.

The span model, tail sampling, async sessions, and cost accounting were built in
parallel and individually tested. These tests pin that they compose correctly
together, which is where parallel features tend to break.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.session import Session  # noqa: E402
from promptetheus.session_async import AsyncSession  # noqa: E402


class RecordingTransport:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def send_event(self, event: dict) -> None:
        self.events.append(event)

    def send_batch(self, events) -> None:
        self.events.extend(dict(e) for e in events)

    def flush(self, timeout=None) -> None:
        pass


def _span_start(events, name):
    return next(
        e
        for e in events
        if e["type"] == "state_change"
        and e["payload"].get("name") == "span_start"
        and e["payload"].get("span_name") == name
    )


# -- spans + tail sampling --------------------------------------------------


def test_spans_are_kept_in_full_on_tail_sampled_failure():
    t = RecordingTransport()
    with Session(agent="a", user_goal="g", session_id="s1", transport=t, tail_sample=True) as s:
        with s.span("outer"):
            inner_event = s.agent_message("inside outer")
            assert "span_id" in inner_event  # stamped live even while buffered
        s.goal_check(False, ["wrong"])  # marks the session interesting -> kept

    # Buffer flushed because of the failed goal check: span tree survives intact.
    start = _span_start(t.events, "outer")
    kept = [e for e in t.events if e.get("span_id") == start["span_id"]]
    assert any(e["type"] == "agent_message" for e in kept)
    # The agent_message's parent is the span; the span's parent is None (top level).
    msg = next(e for e in t.events if e["type"] == "agent_message")
    assert msg["span_id"] == start["span_id"]
    assert start["parent_id"] is None


def test_boring_success_with_spans_is_dropped():
    t = RecordingTransport()
    with Session(
        agent="a", user_goal="g", session_id="s2", transport=t, tail_sample=True, sample_rate=0.0
    ) as s:
        with s.span("outer"):
            s.agent_message("inside")
    assert t.events == []  # no failure signal + sample_rate 0 -> dropped whole


# -- async + spans ----------------------------------------------------------


def test_async_session_nested_spans_stamp_parent():
    t = RecordingTransport()

    async def run():
        async with AsyncSession(agent="a", user_goal="g", session_id="a1", transport=t) as s:
            async with s.aspan("outer"):
                with s.span("inner"):  # sync span nests under async span
                    return s.agent_message("deep")

    deep = asyncio.run(run())
    outer = _span_start(t.events, "outer")
    inner = _span_start(t.events, "inner")
    assert outer["parent_id"] is None
    assert inner["parent_id"] == outer["span_id"]
    assert deep["span_id"] == inner["span_id"]
    assert deep["parent_id"] == outer["span_id"]


def test_concurrent_async_sessions_do_not_cross_contaminate_spans():
    ta, tb = RecordingTransport(), RecordingTransport()

    async def worker(session_id, transport, span_name):
        async with AsyncSession(
            agent="a", user_goal="g", session_id=session_id, transport=transport
        ) as s:
            async with s.aspan(span_name):
                await asyncio.sleep(0)  # force interleaving
                s.agent_message(f"msg-{span_name}")
                await asyncio.sleep(0)

    async def run():
        await asyncio.gather(
            worker("sess_a", ta, "alpha"),
            worker("sess_b", tb, "beta"),
        )

    asyncio.run(run())

    # Each session's message is stamped with its own span, never the other's.
    a_start = _span_start(ta.events, "alpha")
    b_start = _span_start(tb.events, "beta")
    a_msg = next(e for e in ta.events if e["type"] == "agent_message")
    b_msg = next(e for e in tb.events if e["type"] == "agent_message")
    assert a_msg["span_id"] == a_start["span_id"]
    assert b_msg["span_id"] == b_start["span_id"]
    assert a_start["span_id"] != b_start["span_id"]


# -- streaming/cost composition is covered in test_cost.py; here we just sanity
#    check cost accumulates from llm_call events a session actually emitted ------


def test_cost_accumulates_from_session_llm_calls():
    from promptetheus import cost as cost_module

    t = RecordingTransport()
    with Session(agent="a", user_goal="g", session_id="c1", transport=t) as s:
        s.llm_call("gpt-4o-mini", input_tokens=1000, output_tokens=500, latency_ms=10)

    llm_events = [e for e in t.events if e["type"] == "llm_call"]
    assert len(llm_events) == 1
    summary = cost_module.accumulate_session_cost(t.events)
    # Known model -> real positive cost, with token totals carried through.
    assert summary.total_usd > 0.0
    assert summary.input_tokens == 1000
    assert summary.output_tokens == 500
    assert summary.llm_calls == 1
