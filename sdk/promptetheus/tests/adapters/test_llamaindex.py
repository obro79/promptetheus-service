"""Tests for the LlamaIndex callback adapter.

Two layers:

- Import-safety + lazy-error contract, which holds whether or not
  llama-index-core is installed: importing
  promptetheus.adapters.llamaindex never requires the extra, the public
  LlamaIndexAdapter factory is lazily exported and callable, and calling it
  without the extra raises a clear RuntimeError mentioning the llamaindex
  extra.
- Real integration (only when llama_index is importable, guarded with
  importlib.util.find_spec): the handler returned by the factory is a genuine
  llama_index.core.callbacks.base_handler.BaseCallbackHandler subclass and is
  driven with real CBEventType / EventPayload values through the documented
  on_event_start / on_event_end callbacks, asserting it emits only public
  Promptetheus events (llm_call / tool_call / tool_result / retrieval) keyed by
  LlamaIndex's event_id, with token usage, latency, and retrieval nodes mapped.

llama-index-core is installed in this environment, so the integration layer is
library-verified here. EventPayload is a str-Enum, so the adapter's string-keyed
payload lookups resolve LlamaIndex's enum-keyed payloads transparently; the real
callbacks below pass enum keys exactly as LlamaIndex does.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.session import Session  # noqa: E402

_HAS_LLAMAINDEX = importlib.util.find_spec("llama_index") is not None

# Event types the LlamaIndex adapter is permitted to emit. Anything outside this
# set means the adapter grew an adapter-only event type, which violates
# "adapters stay thin".
PUBLIC_ADAPTER_EVENT_TYPES = {
    "llm_call",
    "tool_call",
    "tool_result",
    "retrieval",
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


def test_module_imports_without_llamaindex() -> None:
    # Importing the adapter module must not require llama-index.
    importlib.import_module("promptetheus.adapters.llamaindex")


def test_lazy_export_is_callable() -> None:
    from promptetheus.adapters import LlamaIndexAdapter

    assert callable(LlamaIndexAdapter)


@pytest.mark.skipif(
    _HAS_LLAMAINDEX,
    reason="llama-index installed; this asserts the missing-dependency error path",
)
def test_calling_without_llamaindex_raises_clear_error() -> None:
    from promptetheus.adapters import LlamaIndexAdapter

    with pytest.raises(RuntimeError, match="llamaindex"):
        LlamaIndexAdapter()


# -- real callbacks (only when llama_index is importable) -------------------


@pytest.mark.skipif(
    not _HAS_LLAMAINDEX,
    reason="llama_index not installed; skipping real-callback integration",
)
def test_factory_returns_real_base_callback_handler() -> None:
    """The factory returns a genuine LlamaIndex BaseCallbackHandler subclass."""
    from llama_index.core.callbacks import CallbackManager
    from llama_index.core.callbacks.base_handler import BaseCallbackHandler

    from promptetheus.adapters import LlamaIndexAdapter

    handler = LlamaIndexAdapter()
    assert isinstance(handler, BaseCallbackHandler)
    # It must drop into a real CallbackManager without complaint.
    CallbackManager([handler])


@pytest.mark.skipif(
    not _HAS_LLAMAINDEX,
    reason="llama_index not installed; skipping real-callback integration",
)
def test_callbacks_emit_public_events_keyed_by_event_id() -> None:
    """Driving the real callbacks emits only public events keyed by event_id."""
    from llama_index.core.callbacks.schema import CBEventType, EventPayload

    from promptetheus.adapters import LlamaIndexAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    handler = LlamaIndexAdapter(session)

    # -- LLM lifecycle: model from SERIALIZED, usage from a raw provider response.
    class _Raw:
        usage = {"prompt_tokens": 11, "completion_tokens": 7}

    class _Response:
        raw = _Raw()
        additional_kwargs: dict[str, Any] = {}

    handler.on_event_start(
        CBEventType.LLM,
        {EventPayload.SERIALIZED: {"model": "gpt-4o-mini"}},
        event_id="llm-1",
    )
    handler.on_event_end(
        CBEventType.LLM,
        {EventPayload.RESPONSE: _Response()},
        event_id="llm-1",
    )

    # -- Function-call lifecycle.
    handler.on_event_start(
        CBEventType.FUNCTION_CALL,
        {EventPayload.FUNCTION_CALL: {"name": "search", "args": "rooms"}},
        event_id="fn-1",
    )
    handler.on_event_end(
        CBEventType.FUNCTION_CALL,
        {EventPayload.FUNCTION_OUTPUT: "found 3"},
        event_id="fn-1",
    )

    # -- Retrieve lifecycle: query on start, NodeWithScore nodes on end.
    class _Node:
        node_id = "n1"

        def get_content(self) -> str:
            return "doc text"

    class _NodeWithScore:
        node = _Node()
        score = 0.9

    handler.on_event_start(
        CBEventType.RETRIEVE,
        {EventPayload.QUERY_STR: "rooms"},
        event_id="ret-1",
    )
    handler.on_event_end(
        CBEventType.RETRIEVE,
        {EventPayload.NODES: [_NodeWithScore()]},
        event_id="ret-1",
    )

    # Only public event types were emitted.
    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    # llm_call carries model, mapped token usage, and a latency; raw prompt
    # content never reaches the payload.
    llm_calls = _events_of(transport, "llm_call")
    assert len(llm_calls) == 1
    llm_payload = llm_calls[0]["payload"]
    assert llm_payload["model"] == "gpt-4o-mini"
    assert llm_payload["input_tokens"] == 11
    assert llm_payload["output_tokens"] == 7
    assert "latency_ms" in llm_payload
    assert llm_calls[0]["metadata"]["event_id"] == "llm-1"

    # tool_call uses event_id as call_id and correlates with tool_result.
    tool_calls = _events_of(transport, "tool_call")
    tool_results = _events_of(transport, "tool_result")
    assert len(tool_calls) == 1
    assert len(tool_results) == 1
    assert tool_calls[0]["payload"]["tool_name"] == "search"
    assert tool_calls[0]["payload"]["call_id"] == "fn-1"
    assert tool_results[0]["payload"]["call_id"] == "fn-1"
    assert tool_results[0]["payload"]["result"] == "found 3"

    # retrieval maps NodeWithScore objects into plain document dicts.
    retrievals = _events_of(transport, "retrieval")
    assert len(retrievals) == 1
    ret_payload = retrievals[0]["payload"]
    assert ret_payload["query"] == "rooms"
    assert ret_payload["documents"] == [
        {"id": "n1", "score": 0.9, "content": "doc text"}
    ]


@pytest.mark.skipif(
    not _HAS_LLAMAINDEX,
    reason="llama_index not installed; skipping real-callback integration",
)
def test_on_event_start_returns_event_id_for_callback_manager() -> None:
    """on_event_start returns the event_id, as LlamaIndex's manager expects."""
    from llama_index.core.callbacks.schema import CBEventType, EventPayload

    from promptetheus.adapters import LlamaIndexAdapter

    handler = LlamaIndexAdapter(Session(agent="a", user_goal="g"))
    returned = handler.on_event_start(
        CBEventType.LLM,
        {EventPayload.SERIALIZED: {"model": "m"}},
        event_id="abc",
    )
    assert returned == "abc"
