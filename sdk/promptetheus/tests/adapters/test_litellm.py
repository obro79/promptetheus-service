"""Tests for the LiteLLM callback adapter.

litellm is NOT installed in CI. These tests therefore cover two things:

1. The import-safety + lazy-error contract:
   - importing promptetheus.adapters.litellm succeeds with litellm absent;
   - the public LiteLLMAdapter symbol is lazily exported from
     promptetheus.adapters and is callable;
   - *constructing* the adapter without litellm installed raises a clear
     RuntimeError mentioning the litellm extra (the library is never imported
     at module-import time).

2. The behavioral contract, exercised against a *mock* litellm module injected
   into sys.modules. The mock mirrors the documented LiteLLM CustomLogger:
   a CustomLogger base class and a litellm.callbacks list the adapter registers
   on. We then invoke the logger's documented
   log_success_event(kwargs, response_obj, start_time, end_time) signature and
   assert the adapter stays thin -- it emits only a public llm_call event
   carrying model, prompt/completion token usage, and measured latency -- and
   that detach() removes the logger from litellm.callbacks.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from datetime import datetime, timedelta
from typing import Any

import pytest

from promptetheus.session import Session


_HAS_LITELLM = importlib.util.find_spec("litellm") is not None


# Event types the LiteLLM adapter is permitted to emit. Anything outside this
# set means the adapter grew an adapter-only event type, violating thinness.
PUBLIC_ADAPTER_EVENT_TYPES = {
    "llm_call",
    "tool_call",
    "tool_result",
    "agent_message",
    "retrieval",
    "score",
    "metric",
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


# -- import-safety + lazy-error contract (litellm absent) ------------------


def test_import_does_not_require_litellm() -> None:
    """Importing the adapter module must not require litellm installed."""
    module = importlib.import_module("promptetheus.adapters.litellm")
    assert hasattr(module, "LiteLLMAdapter")


def test_lazy_export_is_callable() -> None:
    """LiteLLMAdapter is lazily exported from promptetheus.adapters and callable."""
    from promptetheus.adapters import LiteLLMAdapter

    assert callable(LiteLLMAdapter)


@pytest.mark.skipif(
    _HAS_LITELLM,
    reason="litellm is installed; lazy-error contract only holds when absent",
)
def test_construct_raises_clear_runtimeerror_without_litellm() -> None:
    """Constructing the adapter without litellm raises a clear RuntimeError."""
    from promptetheus.adapters import LiteLLMAdapter

    with pytest.raises(RuntimeError) as excinfo:
        LiteLLMAdapter()
    assert "litellm" in str(excinfo.value).lower()


@pytest.mark.skipif(
    _HAS_LITELLM,
    reason="litellm is installed; lazy-error contract only holds when absent",
)
def test_construct_raises_even_with_explicit_session() -> None:
    """The lazy-error fires before any session work, even with a session passed."""
    from promptetheus.adapters import LiteLLMAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)

    with pytest.raises(RuntimeError) as excinfo:
        LiteLLMAdapter(session)
    assert "litellm" in str(excinfo.value).lower()
    # No telemetry should have been emitted by a failed adapter construction.
    assert transport.events == []


# -- behavioral contract against a mock litellm module ---------------------


class _MockUsage:
    """OpenAI-shaped usage block, as LiteLLM returns it on response.usage."""

    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _MockResponse:
    """Minimal stand-in for a LiteLLM ModelResponse."""

    def __init__(self, model: str, usage: _MockUsage) -> None:
        self.model = model
        self.usage = usage


class _MockCustomLogger:
    """Stand-in for litellm.integrations.custom_logger.CustomLogger.

    Mirrors the documented base: a no-arg __init__ and the log_success_event /
    async_log_success_event hooks the adapter overrides. Provides default no-op
    hooks so the base contract is faithful.
    """

    def __init__(self) -> None:
        pass

    def log_success_event(
        self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any
    ) -> None:  # pragma: no cover - overridden by the adapter subclass
        pass


def _install_mock_litellm() -> Any:
    """Build a mock litellm module exposing CustomLogger + a callbacks list."""
    import types

    module = types.ModuleType("litellm")
    module.CustomLogger = _MockCustomLogger  # type: ignore[attr-defined]
    module.callbacks = []  # type: ignore[attr-defined]
    return module


@pytest.fixture()
def mock_litellm(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Inject a mock litellm module and reload the adapter against it."""
    module = _install_mock_litellm()
    monkeypatch.setitem(sys.modules, "litellm", module)
    # Reload the adapter so any module-level state is clean; the adapter imports
    # litellm lazily, so this picks up the injected module on construction.
    adapter_module = importlib.reload(
        importlib.import_module("promptetheus.adapters.litellm")
    )
    try:
        yield module, adapter_module
    finally:
        # Restore a clean adapter module for other tests (monkeypatch removes the
        # mock litellm from sys.modules automatically).
        importlib.reload(adapter_module)


def test_success_event_emits_single_public_llm_call(mock_litellm: Any) -> None:
    """log_success_event emits exactly one public llm_call with model/usage/latency."""
    litellm_module, adapter_module = mock_litellm

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)

    handle = adapter_module.LiteLLMAdapter(session)

    # The adapter registered its logger on litellm.callbacks.
    assert len(litellm_module.callbacks) == 1
    registered_logger = litellm_module.callbacks[0]

    # Drive the documented CustomLogger.log_success_event signature.
    start = datetime(2026, 1, 1, 0, 0, 0)
    end = start + timedelta(milliseconds=250)
    response = _MockResponse("gpt-4o-mini", _MockUsage(prompt_tokens=11, completion_tokens=7))
    registered_logger.log_success_event(
        kwargs={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]},
        response_obj=response,
        start_time=start,
        end_time=end,
    )

    # Only public event types were emitted, and exactly one llm_call.
    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    llm_calls = _events_of(transport, "llm_call")
    assert len(llm_calls) == 1
    payload = llm_calls[0]["payload"]
    assert payload["model"] == "gpt-4o-mini"
    assert payload["input_tokens"] == 11
    assert payload["output_tokens"] == 7
    assert payload["latency_ms"] == 250
    # Raw prompt content never reaches the event stream.
    assert "hello" not in repr(payload)


def test_detach_removes_logger_from_callbacks(mock_litellm: Any) -> None:
    """detach() (and the context manager) removes the logger from litellm.callbacks."""
    litellm_module, adapter_module = mock_litellm

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)

    handle = adapter_module.LiteLLMAdapter(session)
    assert len(litellm_module.callbacks) == 1

    handle.detach()
    assert litellm_module.callbacks == []

    # Idempotent: a second detach is a no-op and never raises.
    handle.detach()
    assert litellm_module.callbacks == []

    # Events after detach are swallowed (the logger no-ops once stopped).
    response = _MockResponse("gpt-4o", _MockUsage(1, 1))
    handle._logger.log_success_event(
        kwargs={"model": "gpt-4o"},
        response_obj=response,
        start_time=0.0,
        end_time=1.0,
    )
    assert _events_of(transport, "llm_call") == []


def test_context_manager_detaches(mock_litellm: Any) -> None:
    """Using the adapter as a context manager registers then deregisters."""
    litellm_module, adapter_module = mock_litellm

    session = Session(agent="agent", user_goal="goal", transport=RecordingTransport())

    with adapter_module.LiteLLMAdapter(session) as handle:
        assert len(litellm_module.callbacks) == 1
        assert handle is not None
    assert litellm_module.callbacks == []


def test_malformed_success_event_never_raises(mock_litellm: Any) -> None:
    """A malformed response/usage shape degrades gracefully (model 'unknown')."""
    litellm_module, adapter_module = mock_litellm

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    handle = adapter_module.LiteLLMAdapter(session)
    logger = litellm_module.callbacks[0]

    # No model anywhere, no usage, latency markers of an unsupported type.
    logger.log_success_event(
        kwargs={},
        response_obj=object(),
        start_time=None,
        end_time=None,
    )

    llm_calls = _events_of(transport, "llm_call")
    assert len(llm_calls) == 1
    payload = llm_calls[0]["payload"]
    assert payload["model"] == "unknown"
    assert "input_tokens" not in payload
    assert "output_tokens" not in payload
    assert "latency_ms" not in payload


# -- lib-verified contract against the REAL litellm package ----------------
#
# These run only when litellm is actually installed. They import the real
# library and assert the adapter wraps its real surface (registers a genuine
# litellm CustomLogger on the real litellm.callbacks list, drives the real
# documented log_success_event signature, and emits one public llm_call) rather
# than a mock stand-in. With litellm absent they skip, leaving the mock-based
# behavioral coverage above as the portable contract.


@pytest.mark.skipif(
    not _HAS_LITELLM,
    reason="litellm not installed; lib-verified path requires the real package",
)
def test_lib_logger_is_real_litellm_custom_logger() -> None:
    """The registered logger is a genuine litellm CustomLogger on litellm.callbacks."""
    import litellm
    from litellm.integrations.custom_logger import CustomLogger

    from promptetheus.adapters import LiteLLMAdapter

    session = Session(agent="agent", user_goal="goal", transport=RecordingTransport())
    handle = LiteLLMAdapter(session)
    try:
        assert handle._logger in litellm.callbacks
        assert isinstance(handle._logger, CustomLogger)
    finally:
        handle.detach()
    assert handle._logger not in litellm.callbacks


@pytest.mark.skipif(
    not _HAS_LITELLM,
    reason="litellm not installed; lib-verified path requires the real package",
)
def test_lib_success_event_emits_single_public_llm_call() -> None:
    """Driving the real CustomLogger.log_success_event emits one public llm_call."""
    import litellm

    from promptetheus.adapters import LiteLLMAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)

    with LiteLLMAdapter(session) as handle:
        registered = [cb for cb in litellm.callbacks if cb is handle._logger]
        assert len(registered) == 1
        logger = registered[0]

        start = datetime(2026, 1, 1, 0, 0, 0)
        end = start + timedelta(milliseconds=180)
        response = _MockResponse("gpt-4o-mini", _MockUsage(prompt_tokens=9, completion_tokens=3))
        logger.log_success_event(
            kwargs={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            response_obj=response,
            start_time=start,
            end_time=end,
        )

    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    llm_calls = _events_of(transport, "llm_call")
    assert len(llm_calls) == 1
    payload = llm_calls[0]["payload"]
    assert payload["model"] == "gpt-4o-mini"
    assert payload["input_tokens"] == 9
    assert payload["output_tokens"] == 3
    assert payload["latency_ms"] == 180
    assert "hi" not in repr(payload)
