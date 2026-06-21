"""Testing utilities for asserting on the events your instrumentation emits.

These helpers let SDK users verify the trace their code produces without a
running server. capture_session opens a real Promptetheus Session backed by an
in-memory recording transport and hands back both the live Session and a
growing list of the events it emits, so a test can drive its agent code and then
assert on the timeline:

    from promptetheus.testing import capture_session

    with capture_session(agent="a", user_goal="g") as cap:
        cap.session.user_message("hello")
        cap.session.llm_call("gpt-4o", input_tokens=10, output_tokens=5)

    assert cap.event_types.count("llm_call") == 1
    assert cap.of_type("llm_call")[0]["payload"]["model"] == "gpt-4o"

Nothing here requires pytest. A pytest fixture factory, promptetheus_session, is
also provided for users who prefer a fixture; it imports pytest lazily so this
module imports fine in a runtime without pytest installed.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from .session import Session


class RecordingTransport:
    """Minimal in-memory transport that records every event it is sent.

    Used by capture_session to keep the whole emitted timeline in memory.
    Implements only what Session needs: send_event, send_batch (for tail
    sampling), and flush. It deliberately has no create_trace method, so
    Session skips trace creation entirely and no network or storage is touched.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flush_count = 0

    def send_event(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))

    def send_batch(self, events: Any) -> None:
        for event in events:
            self.events.append(dict(event))

    def flush(self, timeout: float | None = None) -> None:
        self.flush_count += 1


class CapturedEvents:
    """A live view over the events recorded by a capture_session block.

    Wraps the recording transport's event list and the active Session. The
    events list grows as the session emits, so reading cap.events inside the
    with-block reflects everything emitted so far. Convenience accessors filter
    by event type without the caller writing list comprehensions.
    """

    def __init__(self, session: Session, transport: RecordingTransport) -> None:
        self.session = session
        self._transport = transport

    @property
    def events(self) -> list[dict[str, Any]]:
        """All recorded events, in emission order."""

        return self._transport.events

    @property
    def event_types(self) -> list[str]:
        """The type of every recorded event, in emission order.

        Convenient for assertions like cap.event_types.count("llm_call") or
        "goal_check" in cap.event_types.
        """

        return [event["type"] for event in self._transport.events]

    def types(self) -> list[str]:
        """The type of every recorded event, in emission order.

        Method form of event_types, kept for callers who prefer cap.types().
        """

        return self.event_types

    def of_type(self, type: str) -> list[dict[str, Any]]:
        """Every recorded event whose type matches, in emission order."""

        return [event for event in self._transport.events if event.get("type") == type]

    def count(self, type: str) -> int:
        """How many recorded events have the given type."""

        return sum(1 for event in self._transport.events if event.get("type") == type)

    def last(self, type: str) -> dict[str, Any] | None:
        """The most recently recorded event of the given type, or None."""

        for event in reversed(self._transport.events):
            if event.get("type") == type:
                return event
        return None

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._transport.events)

    def __len__(self) -> int:
        return len(self._transport.events)


@contextmanager
def capture_session(**session_kwargs: Any) -> Iterator[CapturedEvents]:
    """Open a Session backed by an in-memory recording transport.

    Yields a CapturedEvents object exposing the live Session (cap.session) and
    the captured events (cap.events / cap.event_types / cap.of_type(...)). All
    session keyword arguments are forwarded to Session. transport and the
    transport-only knobs endpoint, api_key, and spool_dir are dropped, since the
    recording transport is always used so nothing leaves the process. agent and
    user_goal default to test placeholders when omitted so a quick assertion
    needs no boilerplate.

    The Session is entered on enter (emitting state_change session_started) and
    exited on leave (emitting session_end and flushing), exactly like a normal
    with trace.start(...) block, so the captured timeline matches production.
    """

    for transport_only in ("transport", "endpoint", "api_key", "spool_dir"):
        session_kwargs.pop(transport_only, None)
    session_kwargs.setdefault("agent", "test-agent")
    session_kwargs.setdefault("user_goal", "test goal")

    transport = RecordingTransport()
    session = Session(transport=transport, **session_kwargs)
    captured = CapturedEvents(session, transport)
    with session:
        yield captured


def promptetheus_session_fixture(**session_kwargs: Any) -> Any:
    """Build a pytest fixture that yields a CapturedEvents for each test.

    Re-export the result from your conftest or test module to get a fixture
    your tests can request by name:

        from promptetheus.testing import promptetheus_session_fixture

        promptetheus_session = promptetheus_session_fixture()

        def test_emits_goal_check(promptetheus_session):
            promptetheus_session.session.goal_check(passed=True)
            assert promptetheus_session.count("goal_check") == 1

    pytest is imported lazily here, so importing promptetheus.testing never
    requires pytest; only calling this factory does. Any session keyword
    arguments are forwarded to capture_session.
    """

    try:
        import pytest
    except ImportError as exc:  # pragma: no cover - exercised only without pytest
        raise RuntimeError(
            "promptetheus_session_fixture requires pytest. Install it with: pip install pytest"
        ) from exc

    @pytest.fixture
    def promptetheus_session() -> Iterator[CapturedEvents]:
        with capture_session(**session_kwargs) as captured:
            yield captured

    return promptetheus_session


# A ready-to-use fixture for the common case (default agent/user_goal). Importing
# this requires pytest because it is built at import time; users who need this
# module without pytest should use capture_session or the factory instead.
try:  # pragma: no cover - trivial guard
    promptetheus_session = promptetheus_session_fixture()
except RuntimeError:  # pragma: no cover - only when pytest is absent
    promptetheus_session = None


__all__ = [
    "CapturedEvents",
    "RecordingTransport",
    "capture_session",
    "promptetheus_session",
    "promptetheus_session_fixture",
]
