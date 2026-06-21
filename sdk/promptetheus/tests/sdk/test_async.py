from __future__ import annotations

import asyncio

import pytest

from promptetheus import AsyncSession
from promptetheus.session import current


class RecordingTransport:
    """Synchronous, non-blocking transport that records events for assertions."""

    def __init__(self):
        self.events = []
        self.flush_count = 0
        self.traces = []

    def create_trace(self, metadata):
        self.traces.append(dict(metadata))

    def send_event(self, event):
        self.events.append(dict(event))

    def flush(self, timeout=None):
        self.flush_count += 1


class AsyncFlushTransport:
    """Transport whose flush is awaitable, to exercise the async flush path."""

    def __init__(self):
        self.events = []
        self.flush_count = 0

    def send_event(self, event):
        self.events.append(dict(event))

    async def flush(self, timeout=None):
        await asyncio.sleep(0)
        self.flush_count += 1


def _by_type(events, type_):
    return [e for e in events if e["type"] == type_]


def test_async_session_records_basic_events():
    transport = RecordingTransport()

    async def run():
        async with AsyncSession(
            agent="a", user_goal="g", session_id="s1", transport=transport
        ) as session:
            session.user_message("hello")
            session.tool_call("search", {"q": "x"}, call_id="c1")
            session.tool_result("c1", result="ok")
        return session

    asyncio.run(run())

    types = [e["type"] for e in transport.events]
    assert "state_change" in types  # session_started
    assert "user_message" in types
    assert "tool_call" in types
    assert "tool_result" in types
    # __aexit__ must emit a terminal session_end and flush.
    ends = _by_type(transport.events, "session_end")
    assert len(ends) == 1
    assert ends[0]["payload"]["status"] == "completed"
    assert transport.flush_count >= 1


def test_async_session_envelope_is_well_formed():
    transport = RecordingTransport()

    async def run():
        async with AsyncSession(
            agent="a", user_goal="g", session_id="s1", transport=transport
        ) as session:
            session.user_message("hi")

    asyncio.run(run())

    msg = _by_type(transport.events, "user_message")[0]
    assert msg["session_id"] == "s1"
    assert isinstance(msg["seq"], int)
    assert msg["idempotency_key"].startswith("s1:")
    assert msg["payload"]["content"] == "hi"


def test_async_session_nested_span_builds_tree():
    transport = RecordingTransport()

    async def run():
        async with AsyncSession(
            agent="a", user_goal="g", session_id="s1", transport=transport
        ) as session:
            async with session.aspan("outer") as outer_id:
                session.agent_message("in-outer")
                async with session.aspan("inner") as inner_id:
                    session.agent_message("in-inner")
                session.agent_message("back-in-outer")
            return outer_id, inner_id

    outer_id, inner_id = asyncio.run(run())
    assert outer_id != inner_id

    outer_msgs = [
        e for e in _by_type(transport.events, "agent_message") if e["span_id"] == outer_id
    ]
    inner_msgs = [
        e for e in _by_type(transport.events, "agent_message") if e["span_id"] == inner_id
    ]

    assert {e["payload"]["content"] for e in outer_msgs} == {"in-outer", "back-in-outer"}
    assert all(e["parent_id"] is None for e in outer_msgs)

    assert {e["payload"]["content"] for e in inner_msgs} == {"in-inner"}
    assert all(e["parent_id"] == outer_id for e in inner_msgs)


def test_aspan_and_sync_span_nest_together():
    transport = RecordingTransport()

    async def run():
        async with AsyncSession(
            agent="a", user_goal="g", session_id="s1", transport=transport
        ) as session:
            async with session.aspan("outer") as outer_id:
                with session.span("inner") as inner_id:
                    session.agent_message("deep")
            return outer_id, inner_id

    outer_id, inner_id = asyncio.run(run())
    deep = _by_type(transport.events, "agent_message")[0]
    assert deep["span_id"] == inner_id
    assert deep["parent_id"] == outer_id


def test_async_session_failure_emits_failed_session_end():
    transport = RecordingTransport()

    class Boom(Exception):
        pass

    async def run():
        async with AsyncSession(
            agent="a", user_goal="g", session_id="s1", transport=transport
        ):
            raise Boom("nope")

    with pytest.raises(Boom):
        asyncio.run(run())

    end = _by_type(transport.events, "session_end")[0]
    assert end["payload"]["status"] == "failed"
    assert "Boom" in (end["payload"].get("error") or "")


def test_async_session_sets_and_clears_current():
    transport = RecordingTransport()

    seen = {}

    async def run():
        async with AsyncSession(
            agent="a", user_goal="g", session_id="s1", transport=transport
        ) as session:
            seen["inside"] = current()
            seen["inside_id"] = current().session_id
            assert seen["inside"] is session

    asyncio.run(run())
    # Outside the session the current() is a NoopSession.
    assert current().session_id == "noop"
    assert seen["inside_id"] == "s1"


def test_async_flush_awaits_awaitable_transport_flush():
    transport = AsyncFlushTransport()

    async def run():
        session = AsyncSession(
            agent="a", user_goal="g", session_id="s1", transport=transport
        )
        async with session:
            session.user_message("hi")

    asyncio.run(run())
    # The awaitable flush ran at least once (via __aexit__).
    assert transport.flush_count >= 1
    assert any(e["type"] == "user_message" for e in transport.events)


def test_end_async_flushes_without_context_manager():
    transport = RecordingTransport()

    async def run():
        session = AsyncSession(
            agent="a", user_goal="g", session_id="s1", transport=transport
        )
        # Drive lifecycle manually (no async with).
        await session.__aenter__()
        session.user_message("hi")
        await session.end_async("completed")

    asyncio.run(run())
    assert _by_type(transport.events, "session_end")[0]["payload"]["status"] == "completed"
    assert transport.flush_count >= 1
