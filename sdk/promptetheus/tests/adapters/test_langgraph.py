"""Tests for the LangGraph callback adapter.

LangGraph runs on LangChain's callback system, and langchain_core may not be
installed in CI. These tests therefore focus first on the import-safety and
lazy-error contract of the adapter:

- importing promptetheus.adapters.langgraph succeeds with LangChain absent;
- the public LangGraphAdapter factory is lazily exported from
  promptetheus.adapters and is callable;
- calling the factory without LangChain installed raises a clear RuntimeError
  mentioning the langgraph extra (it never imports LangChain at module-import
  time).

When langchain_core is importable (guarded with importlib.util.find_spec), an
extra test additionally builds the handler and drives its callbacks against a
real Session + RecordingTransport, asserting the adapter stays thin: it emits
only public event types (llm_call/tool_call/tool_result plus span state_change
events) and keys them by LangChain's run_id, with graph-node chains nesting
their events under a span.
"""

from __future__ import annotations

import importlib
import importlib.util
import uuid
from typing import Any

import pytest

from promptetheus.session import Session


_HAS_LANGCHAIN_CORE = importlib.util.find_spec("langchain_core") is not None


# Event types the LangGraph adapter is permitted to emit. Anything outside this
# set means the adapter grew an adapter-only event type, which violates
# "adapters stay thin". state_change covers Session.span's span_start/span_end.
PUBLIC_ADAPTER_EVENT_TYPES = {
    "llm_call",
    "tool_call",
    "tool_result",
    "agent_message",
    "user_message",
    "retrieval",
    "metric",
    "score",
    "state_change",
}


class RecordingTransport:
    """In-memory transport that captures every enveloped event the session emits."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flushed = False

    def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def flush(self, timeout: float | None = None) -> None:
        self.flushed = True


def _events_of(transport: RecordingTransport, event_type: str) -> list[dict[str, Any]]:
    return [e for e in transport.events if e["type"] == event_type]


# -- import-safety + lazy-error contract (LangChain absent) ----------------


def test_import_does_not_require_langchain() -> None:
    """Importing the adapter module must not require langchain installed."""
    module = importlib.import_module("promptetheus.adapters.langgraph")
    assert hasattr(module, "LangGraphAdapter")


def test_lazy_export_is_callable() -> None:
    """LangGraphAdapter is lazily exported from promptetheus.adapters and callable."""
    from promptetheus.adapters import LangGraphAdapter

    assert callable(LangGraphAdapter)


@pytest.mark.skipif(
    _HAS_LANGCHAIN_CORE,
    reason="langchain_core is installed; lazy-error contract only holds when absent",
)
def test_factory_raises_clear_runtimeerror_without_langchain() -> None:
    """Calling the factory without LangChain raises a clear RuntimeError."""
    from promptetheus.adapters import LangGraphAdapter

    with pytest.raises(RuntimeError) as excinfo:
        LangGraphAdapter()
    assert "langgraph" in str(excinfo.value).lower()


@pytest.mark.skipif(
    _HAS_LANGCHAIN_CORE,
    reason="langchain_core is installed; lazy-error contract only holds when absent",
)
def test_factory_raises_even_with_explicit_session() -> None:
    """The lazy-error fires before any session work, even with a session passed."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)

    with pytest.raises(RuntimeError) as excinfo:
        LangGraphAdapter = importlib.import_module(
            "promptetheus.adapters.langgraph"
        ).LangGraphAdapter
        LangGraphAdapter(session)
    assert "langgraph" in str(excinfo.value).lower()
    # No telemetry should have been emitted by a failed handler construction.
    assert transport.events == []


# -- real callbacks (only when langchain_core is importable) ----------------


@pytest.mark.skipif(
    not _HAS_LANGCHAIN_CORE,
    reason="langchain_core not installed; skipping live-callback test",
)
def test_callbacks_emit_public_events_keyed_by_run_id() -> None:
    """Driving the handler's callbacks emits only public events keyed by run_id.

    Models a small graph node (chain) that makes one LLM call and one tool call.
    Asserts the adapter (a) emits only public event types, (b) keys LLM/tool
    events by LangChain's run_id, and (c) nests the node's events under a
    Session.span opened by on_chain_start.
    """
    from promptetheus.adapters import LangGraphAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    handler = LangGraphAdapter(session)

    # -- Graph node (chain) opens a span around the node's work.
    chain_run_id = uuid.uuid4()
    handler.on_chain_start(
        {"name": "planner"}, {"input": "go"}, run_id=chain_run_id, name="planner"
    )

    # -- LLM lifecycle: on_llm_start then on_llm_end with a fake LLMResult-ish.
    llm_run_id = uuid.uuid4()
    serialized = {"kwargs": {"model": "gpt-4o-mini"}}

    class _FakeLLMResult:
        """Minimal stand-in for a langchain LLMResult."""

        llm_output = {"token_usage": {"prompt_tokens": 11, "completion_tokens": 7}}
        generations: list[Any] = []

    handler.on_llm_start(serialized, ["hello"], run_id=llm_run_id)
    handler.on_llm_end(_FakeLLMResult(), run_id=llm_run_id)

    # -- Tool lifecycle: on_tool_start then on_tool_end.
    tool_run_id = uuid.uuid4()
    handler.on_tool_start({"name": "search"}, "query string", run_id=tool_run_id)
    handler.on_tool_end("tool output", run_id=tool_run_id)

    # -- Node finishes: close the span.
    handler.on_chain_end({"output": "done"}, run_id=chain_run_id)

    # Only public event types were emitted.
    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    # The node opened and closed a span (state_change span_start/span_end).
    state_changes = _events_of(transport, "state_change")
    span_names = {sc["payload"].get("name") for sc in state_changes}
    assert "span_start" in span_names
    assert "span_end" in span_names
    span_starts = [sc for sc in state_changes if sc["payload"].get("name") == "span_start"]
    assert any(sc["payload"].get("span_name") == "planner" for sc in span_starts)

    # llm_call carries model + token usage; raw prompt content is NOT in payload.
    llm_calls = _events_of(transport, "llm_call")
    assert len(llm_calls) == 1
    llm_payload = llm_calls[0]["payload"]
    assert llm_payload["model"] == "gpt-4o-mini"
    assert llm_payload["input_tokens"] == 11
    assert llm_payload["output_tokens"] == 7
    assert "hello" not in repr(llm_payload)
    assert llm_calls[0]["metadata"]["run_id"] == str(llm_run_id)
    # The LLM call happened inside the node, so it is stamped with the span id.
    assert "span_id" in llm_calls[0]

    # tool_call uses run_id as call_id and correlates with tool_result.
    tool_calls = _events_of(transport, "tool_call")
    tool_results = _events_of(transport, "tool_result")
    assert len(tool_calls) == 1
    assert len(tool_results) == 1
    assert tool_calls[0]["payload"]["tool_name"] == "search"
    assert tool_calls[0]["payload"]["call_id"] == str(tool_run_id)
    assert tool_results[0]["payload"]["call_id"] == str(tool_run_id)
    assert tool_results[0]["payload"]["result"] == "tool output"
    # Tool events also nested under the node span.
    assert "span_id" in tool_calls[0]


@pytest.mark.skipif(
    not _HAS_LANGCHAIN_CORE,
    reason="langchain_core not installed; skipping live-callback test",
)
def test_defaults_to_current_session() -> None:
    """With no explicit session the handler records into promptetheus.current()."""
    from promptetheus.adapters import LangGraphAdapter

    transport = RecordingTransport()
    with Session(agent="agent", user_goal="goal", transport=transport):
        handler = LangGraphAdapter()
        run_id = uuid.uuid4()
        handler.on_tool_start({"name": "search"}, "q", run_id=run_id)
        handler.on_tool_end("out", run_id=run_id)

    tool_calls = _events_of(transport, "tool_call")
    assert len(tool_calls) == 1
    assert tool_calls[0]["payload"]["tool_name"] == "search"
