"""Tests for the DSPy callback adapter.

DSPy is NOT installed in this environment, so this adapter is REVIEW-VERIFIED,
not lib-verified: the callback hook names and their signatures exercised below
were checked against the documented dspy.utils.callback.BaseCallback API
(on_lm_start/on_lm_end, on_module_start/on_module_end, on_tool_start/on_tool_end,
with call_id / instance / inputs on start and call_id / outputs / exception on
end). The fakes here mirror those shapes.

The first layer asserts the import-safety + lazy-error contract: importing the
module never requires dspy, the public DSPyAdapter symbol is lazily exported and
callable, and constructing it without dspy raises a clear RuntimeError naming the
dspy extra. The second layer installs a fake dspy module exposing a BaseCallback
base class and drives the adapter's hooks against a real Session +
RecordingTransport, asserting the adapter stays thin: it emits only public event
types and correlates them by DSPy's call_id.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from typing import Any

import pytest

from promptetheus.session import Session

_HAS_DSPY = importlib.util.find_spec("dspy") is not None

# Event types the DSPy adapter is permitted to emit. Anything outside this set
# means the adapter grew an adapter-only event type ("adapters stay thin").
# state_change is included because Session.span emits span_start/span_end
# state_change events, which is the standard nesting mechanism, not an
# adapter-only type.
PUBLIC_ADAPTER_EVENT_TYPES = {
    "llm_call",
    "tool_call",
    "tool_result",
    "agent_message",
    "state_change",
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


def test_module_imports_without_dspy() -> None:
    """Importing the adapter module must not require dspy installed."""
    module = importlib.import_module("promptetheus.adapters.dspy")
    assert hasattr(module, "DSPyAdapter")


def test_lazy_export_is_callable() -> None:
    """DSPyAdapter is lazily exported from promptetheus.adapters and callable."""
    from promptetheus.adapters import DSPyAdapter

    assert callable(DSPyAdapter)


@pytest.mark.skipif(
    _HAS_DSPY,
    reason="dspy installed; this asserts the missing-dependency error path",
)
def test_calling_without_dspy_raises_clear_error() -> None:
    """Constructing the adapter without dspy raises a clear RuntimeError."""
    from promptetheus.adapters import DSPyAdapter

    with pytest.raises(RuntimeError, match="dspy"):
        DSPyAdapter()


@pytest.mark.skipif(
    _HAS_DSPY,
    reason="dspy installed; lazy-error contract only holds when absent",
)
def test_raises_even_with_explicit_session() -> None:
    """The lazy-error fires before any session work, even with a session passed."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)

    from promptetheus.adapters import DSPyAdapter

    with pytest.raises(RuntimeError, match="dspy"):
        DSPyAdapter(session)
    # No telemetry should have been emitted by a failed construction.
    assert transport.events == []


# -- fakes mirroring the documented dspy.utils.callback.BaseCallback ----------


class _BaseCallback:
    """Mirror of dspy.utils.callback.BaseCallback (no-op default hooks).

    DSPy subclasses override only the hooks they need; the real base class
    provides empty defaults. Our adapter subclasses this and calls super().
    """

    def on_lm_start(self, call_id: str, instance: Any, inputs: dict[str, Any]) -> None:
        pass

    def on_lm_end(self, call_id: str, outputs: Any, exception: Any = None) -> None:
        pass

    def on_module_start(self, call_id: str, instance: Any, inputs: dict[str, Any]) -> None:
        pass

    def on_module_end(self, call_id: str, outputs: Any, exception: Any = None) -> None:
        pass

    def on_tool_start(self, call_id: str, instance: Any, inputs: dict[str, Any]) -> None:
        pass

    def on_tool_end(self, call_id: str, outputs: Any, exception: Any = None) -> None:
        pass


class _FakeLM:
    """Mirror of a dspy.LM instance: exposes a model attribute."""

    def __init__(self, model: str) -> None:
        self.model = model


class _FakeModule:
    """Stand-in for a dspy.Module instance (named via its class)."""


class _FakeTool:
    """Mirror of a dspy.Tool: exposes a name attribute."""

    def __init__(self, name: str) -> None:
        self.name = name


@pytest.fixture()
def fake_dspy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a fake dspy package exposing dspy.utils.callback.BaseCallback."""
    dspy_pkg = types.ModuleType("dspy")
    dspy_pkg.__path__ = []  # mark as a package so submodule import resolves
    utils_pkg = types.ModuleType("dspy.utils")
    utils_pkg.__path__ = []
    callback_module = types.ModuleType("dspy.utils.callback")
    callback_module.BaseCallback = _BaseCallback  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "dspy", dspy_pkg)
    monkeypatch.setitem(sys.modules, "dspy.utils", utils_pkg)
    monkeypatch.setitem(sys.modules, "dspy.utils.callback", callback_module)


def _new_adapter(session: Session) -> Any:
    from promptetheus.adapters import DSPyAdapter

    return DSPyAdapter(session)


# -- driving the adapter against the fake BaseCallback -----------------------


def test_adapter_subclasses_base_callback(fake_dspy: None) -> None:
    """The constructed adapter is a BaseCallback subclass instance."""
    session = Session(agent="agent", user_goal="goal", transport=RecordingTransport())
    adapter = _new_adapter(session)
    assert isinstance(adapter, _BaseCallback)


def test_hooks_emit_public_events_correlated_by_call_id(fake_dspy: None) -> None:
    """Driving the callback hooks emits only public events keyed by call_id."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = _new_adapter(session)

    # -- LM lifecycle: on_lm_start then on_lm_end with usage on the output.
    adapter.on_lm_start("lm-1", _FakeLM("openai/gpt-4o-mini"), {"prompt": "hi"})
    adapter.on_lm_end(
        "lm-1",
        {"usage": {"prompt_tokens": 11, "completion_tokens": 7}},
    )

    # -- Module lifecycle: span open, output, span close.
    adapter.on_module_start("mod-1", _FakeModule(), {"question": "?"})
    adapter.on_module_end("mod-1", {"answer": "forty-two"})

    # -- Tool lifecycle: start then end, same call_id.
    adapter.on_tool_start("tool-1", _FakeTool("search"), {"q": "rooms"})
    adapter.on_tool_end("tool-1", "found 3")

    # Only public event types were emitted.
    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    # llm_call carries model + mapped usage and the call_id; raw prompt is absent.
    llm_calls = _events_of(transport, "llm_call")
    assert len(llm_calls) == 1
    assert llm_calls[0]["payload"]["model"] == "openai/gpt-4o-mini"
    assert llm_calls[0]["payload"]["input_tokens"] == 11
    assert llm_calls[0]["payload"]["output_tokens"] == 7
    assert llm_calls[0]["metadata"]["call_id"] == "lm-1"
    assert "hi" not in repr(llm_calls[0]["payload"])

    # The module opened a span (span_start/span_end state_change) named _FakeModule.
    span_starts = [
        e
        for e in _events_of(transport, "state_change")
        if e["payload"].get("name") == "span_start"
    ]
    span_ends = [
        e
        for e in _events_of(transport, "state_change")
        if e["payload"].get("name") == "span_end"
    ]
    assert len(span_starts) == 1
    assert len(span_ends) == 1
    assert span_starts[0]["payload"]["span_name"] == "_FakeModule"

    # The module output -> agent_message, emitted inside the span.
    agent_messages = _events_of(transport, "agent_message")
    assert len(agent_messages) == 1
    assert agent_messages[0]["payload"]["content"] == "forty-two"
    assert agent_messages[0].get("span_id") is not None

    # tool_call/tool_result correlate via DSPy's call_id.
    tool_calls = _events_of(transport, "tool_call")
    tool_results = _events_of(transport, "tool_result")
    assert len(tool_calls) == 1
    assert len(tool_results) == 1
    assert tool_calls[0]["payload"]["tool_name"] == "search"
    assert tool_calls[0]["payload"]["arguments"] == {"q": "rooms"}
    assert tool_calls[0]["payload"]["call_id"] == "tool-1"
    assert tool_results[0]["payload"]["call_id"] == "tool-1"
    assert tool_results[0]["payload"]["result"] == "found 3"


def test_failed_lm_call_emits_no_llm_call(fake_dspy: None) -> None:
    """An LM call that ends with an exception drops state without emitting."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = _new_adapter(session)

    adapter.on_lm_start("lm-err", _FakeLM("openai/gpt-4o"), {"prompt": "x"})
    adapter.on_lm_end("lm-err", None, exception=ValueError("boom"))

    assert _events_of(transport, "llm_call") == []


def test_tool_error_maps_to_tool_result_error(fake_dspy: None) -> None:
    """A tool that ends with an exception maps to tool_result(error=...)."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = _new_adapter(session)

    adapter.on_tool_start("tool-err", _FakeTool("search"), {"q": "rooms"})
    adapter.on_tool_end("tool-err", None, exception=ValueError("boom"))

    tool_results = _events_of(transport, "tool_result")
    assert len(tool_results) == 1
    assert tool_results[0]["payload"]["error"] == "boom"
    assert tool_results[0]["payload"]["result"] is None


def test_module_span_closes_even_when_output_unreadable(fake_dspy: None) -> None:
    """A module end with no readable output still closes its span cleanly."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = _new_adapter(session)

    adapter.on_module_start("mod-x", _FakeModule(), {})
    adapter.on_module_end("mod-x", None)

    span_starts = [
        e
        for e in _events_of(transport, "state_change")
        if e["payload"].get("name") == "span_start"
    ]
    span_ends = [
        e
        for e in _events_of(transport, "state_change")
        if e["payload"].get("name") == "span_end"
    ]
    assert len(span_starts) == 1
    assert len(span_ends) == 1
    # No usable output text -> no agent_message.
    assert _events_of(transport, "agent_message") == []


def test_helpers_swallow_session_failures(fake_dspy: None) -> None:
    """A session that raises in a helper never propagates into a DSPy hook."""

    class _BoomSession:
        session_id = "boom"

        def llm_call(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("transport down")

        def tool_call(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("transport down")

        def tool_result(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("transport down")

    adapter = _new_adapter(_BoomSession())  # type: ignore[arg-type]

    # None of these should raise despite the session blowing up.
    adapter.on_lm_start("lm", _FakeLM("m"), {})
    adapter.on_lm_end("lm", {})
    adapter.on_tool_start("t", _FakeTool("search"), {})
    adapter.on_tool_end("t", "out")


# -- lib-verified contract against the REAL dspy package ---------------------
#
# These run only when dspy is actually installed. They import the real
# dspy.utils.callback.BaseCallback and assert the constructed adapter is a
# genuine subclass instance, then drive the real documented hook surface
# (on_lm_start/on_lm_end, on_module_start/on_module_end, on_tool_start/
# on_tool_end) and assert the adapter emits only public events correlated by
# DSPy's call_id. With dspy absent they skip, leaving the fake-BaseCallback
# behavioral coverage above as the portable contract.


@pytest.mark.skipif(
    not _HAS_DSPY,
    reason="dspy not installed; lib-verified path requires the real package",
)
def test_lib_adapter_is_real_base_callback_subclass() -> None:
    """The constructed adapter is an instance of the real dspy BaseCallback."""
    from dspy.utils.callback import BaseCallback

    from promptetheus.adapters import DSPyAdapter

    session = Session(agent="agent", user_goal="goal", transport=RecordingTransport())
    adapter = DSPyAdapter(session)
    assert isinstance(adapter, BaseCallback)


@pytest.mark.skipif(
    not _HAS_DSPY,
    reason="dspy not installed; lib-verified path requires the real package",
)
def test_lib_hooks_emit_public_events_correlated_by_call_id() -> None:
    """Driving the real dspy hook surface emits only public events keyed by call_id."""
    from promptetheus.adapters import DSPyAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = DSPyAdapter(session)

    adapter.on_lm_start("lm-1", _FakeLM("openai/gpt-4o-mini"), {"prompt": "hi"})
    adapter.on_lm_end("lm-1", {"usage": {"prompt_tokens": 11, "completion_tokens": 7}})

    adapter.on_module_start("mod-1", _FakeModule(), {"question": "?"})
    adapter.on_module_end("mod-1", {"answer": "forty-two"})

    adapter.on_tool_start("tool-1", _FakeTool("search"), {"q": "rooms"})
    adapter.on_tool_end("tool-1", "found 3")

    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    llm_calls = _events_of(transport, "llm_call")
    assert len(llm_calls) == 1
    assert llm_calls[0]["payload"]["model"] == "openai/gpt-4o-mini"
    assert llm_calls[0]["payload"]["input_tokens"] == 11
    assert llm_calls[0]["payload"]["output_tokens"] == 7
    assert llm_calls[0]["metadata"]["call_id"] == "lm-1"
    assert "hi" not in repr(llm_calls[0]["payload"])

    agent_messages = _events_of(transport, "agent_message")
    assert len(agent_messages) == 1
    assert agent_messages[0]["payload"]["content"] == "forty-two"

    tool_calls = _events_of(transport, "tool_call")
    tool_results = _events_of(transport, "tool_result")
    assert len(tool_calls) == 1
    assert len(tool_results) == 1
    assert tool_calls[0]["payload"]["tool_name"] == "search"
    assert tool_calls[0]["payload"]["call_id"] == "tool-1"
    assert tool_results[0]["payload"]["call_id"] == "tool-1"
    assert tool_results[0]["payload"]["result"] == "found 3"
