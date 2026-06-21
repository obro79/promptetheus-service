"""Tests for the CrewAI event-bus adapter.

CrewAI has a very heavy dependency tree, so it is NOT installed in this
environment. This adapter is therefore REVIEW-VERIFIED, not lib-verified: the
event class names, their field names, and the event-bus registration protocol
exercised below were checked against the CrewAI source
(crewai.events.event_bus and crewai.events.types.{llm,tool_usage,agent,task}
events), and the fakes here mirror those real shapes:

- The fake bus mimics the real CrewAIEventsBus surface: an on(EventType)
  decorator that registers the wrapped handler, a public
  register_handler(EventType, handler), a public off(EventType, handler), and
  an internal _sync_handlers dict of per-event-type sets. emit(source, event)
  dispatches handler(source, event) exactly as CrewAI does.
- The fake events carry the real pydantic field names: ToolUsageEvent.tool_name
  / tool_args, ToolUsageFinishedEvent.output, ToolUsageErrorEvent.error,
  LLMCallCompletedEvent.model + usage (prompt_tokens / completion_tokens),
  AgentExecutionCompletedEvent.output.

These tests load the adapter module directly from its file path so they run with
CrewAI absent. The first layer still asserts the import-safety + lazy-error
contract; the second drives the adapter against the fake bus.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.session import Session  # noqa: E402

_HAS_CREWAI = importlib.util.find_spec("crewai") is not None

# Event types the CrewAI adapter is permitted to emit. Anything outside this set
# means the adapter grew an adapter-only event type ("adapters stay thin").
PUBLIC_ADAPTER_EVENT_TYPES = {
    "llm_call",
    "tool_call",
    "tool_result",
    "agent_message",
}


class RecordingTransport:
    """In-memory transport capturing every enveloped event the session emits."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flushed = False

    def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def flush(self, timeout: float | None = None) -> None:
        self.flushed = True


def _events_of(transport: RecordingTransport, event_type: str) -> list[dict[str, Any]]:
    return [e for e in transport.events if e["type"] == event_type]


# -- import-safety + lazy-export contract (holds regardless of the extra) ----


def test_module_imports_without_crewai() -> None:
    importlib.import_module("promptetheus.adapters.crewai")


def test_lazy_export_is_callable() -> None:
    from promptetheus.adapters import CrewAIAdapter

    assert callable(CrewAIAdapter)


@pytest.mark.skipif(
    _HAS_CREWAI,
    reason="crewai installed; this asserts the missing-dependency error path",
)
def test_calling_without_crewai_raises_clear_error() -> None:
    from promptetheus.adapters import CrewAIAdapter

    with pytest.raises(RuntimeError, match="crewai"):
        CrewAIAdapter()


# -- fakes mirroring the real CrewAI bus + event shapes (review-verified) ----


class _Event:
    """Base fake CrewAI event: stores arbitrary fields as attributes."""

    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


class LLMCallCompletedEvent(_Event):
    """Mirror of crewai LLMCallCompletedEvent (model + usage dict)."""


class ToolUsageStartedEvent(_Event):
    """Mirror of crewai ToolUsageStartedEvent (tool_name + tool_args)."""


class ToolUsageFinishedEvent(_Event):
    """Mirror of crewai ToolUsageFinishedEvent (tool_name + output)."""


class ToolUsageErrorEvent(_Event):
    """Mirror of crewai ToolUsageErrorEvent (tool_name + error)."""


class AgentExecutionCompletedEvent(_Event):
    """Mirror of crewai AgentExecutionCompletedEvent (output: str)."""


class TaskCompletedEvent(_Event):
    """Mirror of crewai TaskCompletedEvent (output)."""


class _FakeBus:
    """Mirror of the public surface of CrewAI's CrewAIEventsBus.

    Implements on()/register_handler()/off() and an internal _sync_handlers dict
    of per-event-type sets, plus emit(source, event) that dispatches as
    handler(source, event), matching the real bus.
    """

    def __init__(self) -> None:
        self._sync_handlers: dict[type, set] = {}

    def on(self, event_type: type) -> Any:
        def decorator(handler: Any) -> Any:
            self.register_handler(event_type, handler)
            return handler

        return decorator

    def register_handler(self, event_type: type, handler: Any) -> None:
        self._sync_handlers.setdefault(event_type, set()).add(handler)

    def off(self, event_type: type, handler: Any) -> None:
        bucket = self._sync_handlers.get(event_type)
        if bucket is not None:
            bucket.discard(handler)

    def emit(self, source: Any, event: Any) -> None:
        for handler in list(self._sync_handlers.get(type(event), set())):
            handler(source, event)


class _FakeEventsModule(types.ModuleType):
    """Fake crewai.utilities.events module exposing the bus + event classes."""

    def __init__(self, bus: _FakeBus) -> None:
        super().__init__("crewai.utilities.events")
        self.crewai_event_bus = bus
        self.LLMCallCompletedEvent = LLMCallCompletedEvent
        self.ToolUsageStartedEvent = ToolUsageStartedEvent
        self.ToolUsageFinishedEvent = ToolUsageFinishedEvent
        self.ToolUsageErrorEvent = ToolUsageErrorEvent
        self.AgentExecutionCompletedEvent = AgentExecutionCompletedEvent
        self.TaskCompletedEvent = TaskCompletedEvent


@pytest.fixture()
def fake_crewai(monkeypatch: pytest.MonkeyPatch) -> _FakeBus:
    """Install a fake crewai.utilities.events module for the duration of a test."""
    crewai_pkg = types.ModuleType("crewai")
    crewai_pkg.__path__ = []  # mark as a package so submodule import resolves
    utilities_pkg = types.ModuleType("crewai.utilities")
    utilities_pkg.__path__ = []
    bus = _FakeBus()
    events_module = _FakeEventsModule(bus)

    monkeypatch.setitem(sys.modules, "crewai", crewai_pkg)
    monkeypatch.setitem(sys.modules, "crewai.utilities", utilities_pkg)
    monkeypatch.setitem(sys.modules, "crewai.utilities.events", events_module)
    return bus


def _new_adapter(bus_unused: _FakeBus, session: Session) -> Any:
    from promptetheus.adapters import CrewAIAdapter

    return CrewAIAdapter(session)


# -- driving the adapter against the fake bus -------------------------------


def test_registers_and_emits_public_events(fake_crewai: _FakeBus) -> None:
    """Emitting CrewAI events drives only public, correlated Session events."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = _new_adapter(fake_crewai, session)

    # The adapter registered handlers for the families it understands.
    assert LLMCallCompletedEvent in fake_crewai._sync_handlers
    assert ToolUsageStartedEvent in fake_crewai._sync_handlers
    assert ToolUsageFinishedEvent in fake_crewai._sync_handlers

    source = object()

    # -- LLM completion: model + usage(prompt_tokens/completion_tokens).
    fake_crewai.emit(
        source,
        LLMCallCompletedEvent(
            model="gpt-4o",
            usage={"prompt_tokens": 11, "completion_tokens": 7},
        ),
    )

    # -- Tool usage started then finished, same tool_name -> same call_id.
    fake_crewai.emit(
        source,
        ToolUsageStartedEvent(
            tool_name="search", tool_args={"q": "rooms"}, agent_id="a1"
        ),
    )
    fake_crewai.emit(
        source,
        ToolUsageFinishedEvent(tool_name="search", output="found 3", agent_id="a1"),
    )

    # -- Agent step completion -> agent_message.
    fake_crewai.emit(source, AgentExecutionCompletedEvent(output="done"))

    adapter.stop()

    # Only public event types.
    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    # llm_call carries model + mapped usage.
    llm_calls = _events_of(transport, "llm_call")
    assert len(llm_calls) == 1
    assert llm_calls[0]["payload"]["model"] == "gpt-4o"
    assert llm_calls[0]["payload"]["input_tokens"] == 11
    assert llm_calls[0]["payload"]["output_tokens"] == 7

    # tool_call and tool_result correlate via a derived call_id (CrewAI tool
    # events carry no explicit id; the adapter queues by agent + tool_name).
    tool_calls = _events_of(transport, "tool_call")
    tool_results = _events_of(transport, "tool_result")
    assert len(tool_calls) == 1
    assert len(tool_results) == 1
    assert tool_calls[0]["payload"]["tool_name"] == "search"
    assert tool_calls[0]["payload"]["arguments"] == {"q": "rooms"}
    call_id = tool_calls[0]["payload"]["call_id"]
    assert call_id == tool_results[0]["payload"]["call_id"]
    assert call_id  # a real, shared correlation id, not None
    assert tool_results[0]["payload"]["result"] == "found 3"

    # agent step -> agent_message with the step output.
    agent_messages = _events_of(transport, "agent_message")
    assert len(agent_messages) == 1
    assert agent_messages[0]["payload"]["content"] == "done"


def test_repeated_tool_calls_get_unique_correlatable_ids(fake_crewai: _FakeBus) -> None:
    """Repeated same-agent/tool calls must not reuse one static call_id."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = _new_adapter(fake_crewai, session)

    source = object()
    fake_crewai.emit(
        source,
        ToolUsageStartedEvent(
            tool_name="search", tool_args={"q": "rooms"}, agent_id="a1"
        ),
    )
    fake_crewai.emit(
        source,
        ToolUsageStartedEvent(
            tool_name="search", tool_args={"q": "people"}, agent_id="a1"
        ),
    )
    fake_crewai.emit(
        source,
        ToolUsageFinishedEvent(tool_name="search", output="rooms", agent_id="a1"),
    )
    fake_crewai.emit(
        source,
        ToolUsageFinishedEvent(tool_name="search", output="people", agent_id="a1"),
    )
    adapter.stop()

    tool_calls = _events_of(transport, "tool_call")
    tool_results = _events_of(transport, "tool_result")
    assert len(tool_calls) == 2
    assert len(tool_results) == 2

    call_ids = [event["payload"]["call_id"] for event in tool_calls]
    result_ids = [event["payload"]["call_id"] for event in tool_results]
    assert call_ids[0] != call_ids[1]
    assert call_ids == result_ids
    assert all(call_id.startswith("crewai:a1:search:") for call_id in call_ids)


def test_tool_error_maps_to_tool_result_error(fake_crewai: _FakeBus) -> None:
    """A tool-usage-error event maps to tool_result(error=...)."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = _new_adapter(fake_crewai, session)

    fake_crewai.emit(
        object(),
        ToolUsageErrorEvent(tool_name="search", error=ValueError("boom")),
    )
    adapter.stop()

    tool_results = _events_of(transport, "tool_result")
    assert len(tool_results) == 1
    assert tool_results[0]["payload"]["error"] == "boom"
    assert tool_results[0]["payload"]["result"] is None


def test_stop_deregisters_via_off_and_silences_handlers(
    fake_crewai: _FakeBus,
) -> None:
    """stop() removes handlers through the public off() API and emits nothing after."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = _new_adapter(fake_crewai, session)

    adapter.stop()

    # Every registered bucket is now empty: off() removed our handlers.
    assert all(len(bucket) == 0 for bucket in fake_crewai._sync_handlers.values())

    # Even if an event still reached a stale handler, the _stopped guard means
    # no further telemetry is emitted.
    fake_crewai.emit(object(), LLMCallCompletedEvent(model="x", usage={}))
    assert _events_of(transport, "llm_call") == []


def test_context_manager_stops_on_exit(fake_crewai: _FakeBus) -> None:
    """Using the adapter as a context manager deregisters on exit."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)

    from promptetheus.adapters import CrewAIAdapter

    with CrewAIAdapter(session):
        fake_crewai.emit(object(), LLMCallCompletedEvent(model="m", usage={}))

    assert all(len(bucket) == 0 for bucket in fake_crewai._sync_handlers.values())
    assert len(_events_of(transport, "llm_call")) == 1
