from __future__ import annotations

import asyncio
import time
from pathlib import Path

from promptetheus import AsyncSession, Session
import promptetheus.session as session_module


class RecordingTransport:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.flush_count = 0

    def send_event(self, event: dict) -> None:
        self.events.append(dict(event))

    def flush(self, timeout=None) -> None:
        self.flush_count += 1


def _by_type(events: list[dict], type_: str) -> list[dict]:
    return [event for event in events if event["type"] == type_]


def test_custom_redactor_failure_does_not_crash_or_send_unredacted_event() -> None:
    transport = RecordingTransport()

    def boom(event: dict) -> dict:
        raise RuntimeError("redactor exploded")

    session = Session(
        agent="a",
        user_goal="g",
        session_id="s1",
        transport=transport,
        redact=boom,
    )

    event = session.agent_message("secret")

    assert event["payload"]["content"] == "secret"
    assert transport.events == []


def test_validate_event_failure_does_not_crash_or_send_invalid_event(monkeypatch) -> None:
    transport = RecordingTransport()

    def boom(event: dict) -> None:
        raise ValueError("bad envelope")

    monkeypatch.setattr(session_module, "validate_event", boom)
    session = Session(agent="a", user_goal="g", session_id="s1", transport=transport)

    event = session.user_message("hello")

    assert event["payload"]["content"] == "hello"
    assert transport.events == []


def test_flush_no_timeout_fallback_exception_is_swallowed_by_end() -> None:
    class BadFlushTransport(RecordingTransport):
        def flush(self, *args, **kwargs) -> None:
            if kwargs:
                raise TypeError("timeout is unsupported")
            raise RuntimeError("flush failed")

    session = Session(
        agent="a",
        user_goal="g",
        session_id="s1",
        transport=BadFlushTransport(),
    )

    event = session.end("completed")

    assert event["type"] == "session_end"


def test_session_end_is_idempotent() -> None:
    transport = RecordingTransport()
    session = Session(agent="a", user_goal="g", session_id="s1", transport=transport)

    first = session.end("completed")
    second = session.end("failed", error="should not emit")

    assert second == first
    ends = _by_type(transport.events, "session_end")
    assert len(ends) == 1
    assert ends[0]["payload"]["status"] == "completed"


def test_async_session_end_is_idempotent() -> None:
    transport = RecordingTransport()

    async def run() -> tuple[dict, dict]:
        session = AsyncSession(
            agent="a",
            user_goal="g",
            session_id="s1",
            transport=transport,
        )
        await session.__aenter__()
        first = session.end("completed")
        second = await session.end_async("failed", error="should not emit")
        await session.__aexit__(None, None, None)
        return first, second

    first, second = asyncio.run(run())

    assert second == first
    ends = _by_type(transport.events, "session_end")
    assert len(ends) == 1
    assert ends[0]["payload"]["status"] == "completed"


def test_async_flush_runs_sync_transport_in_executor() -> None:
    class SlowFlushTransport(RecordingTransport):
        def flush(self, timeout=None) -> None:
            time.sleep(0.05)
            self.flush_count += 1

    transport = SlowFlushTransport()

    async def run() -> None:
        session = AsyncSession(
            agent="a",
            user_goal="g",
            session_id="s1",
            transport=transport,
        )
        task = asyncio.create_task(session.flush())
        await asyncio.sleep(0.01)
        assert not task.done()
        await task

    asyncio.run(run())
    assert transport.flush_count == 1


def test_async_flush_swallows_sync_transport_exception() -> None:
    class BadFlushTransport(RecordingTransport):
        def flush(self, timeout=None) -> None:
            raise RuntimeError("flush failed")

    async def run() -> None:
        session = AsyncSession(
            agent="a",
            user_goal="g",
            session_id="s1",
            transport=BadFlushTransport(),
        )
        await session.flush()

    asyncio.run(run())


def test_artifact_path_read_errors_do_not_crash_screenshot_or_replay(
    monkeypatch,
) -> None:
    transport = RecordingTransport()
    session = Session(agent="a", user_goal="g", session_id="s1", transport=transport)

    monkeypatch.setattr(Path, "is_file", lambda self: True)

    def unreadable(self: Path) -> bytes:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_bytes", unreadable)

    screenshot = session.screenshot("/tmp/shot.png")
    replay = session.replay_artifact("/tmp/replay.webm")

    assert screenshot["payload"]["source"] == "/tmp/shot.png"
    assert replay["payload"]["source"] == "/tmp/replay.webm"
    assert _by_type(transport.events, "screenshot")
    assert _by_type(transport.events, "replay_artifact")
