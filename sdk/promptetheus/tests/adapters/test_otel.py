"""Tests for the OpenTelemetry export bridge.

Two layers:

- Import-safety + lazy-error contract, which holds whether or not
  opentelemetry is installed: importing promptetheus.adapters.otel never
  requires the extra, the public OpenTelemetryBridge is lazily exported and
  callable, and constructing it without the extra raises a clear RuntimeError.
- Real integration (only when opentelemetry is importable, guarded with
  importlib.util.find_spec): the bridge is driven against a real in-memory
  OTel tracer built from TracerProvider + SimpleSpanProcessor +
  InMemorySpanExporter, asserting that Promptetheus events map to real spans
  with the right names and promptetheus.* attributes, and that every event
  is still emitted on the wrapped Session (Promptetheus stays source of truth).

opentelemetry-api + opentelemetry-sdk are installed in this environment, so
the integration layer is library-verified here.
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

_HAS_OTEL = importlib.util.find_spec("opentelemetry") is not None

# Whenever the otel-sdk in-memory exporter is available we can build a real
# tracer. The api-only install lacks opentelemetry.sdk; guard for both.
_HAS_OTEL_SDK = (
    importlib.util.find_spec("opentelemetry.sdk") is not None if _HAS_OTEL else False
)


class RecordingTransport:
    """In-memory transport capturing every enveloped event the session emits."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flushed = False

    def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def flush(self, timeout: float | None = None) -> None:
        self.flushed = True


def _build_inmemory_tracer() -> tuple[Any, Any]:
    """Return (tracer, exporter) backed by an in-memory OTel span exporter."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("promptetheus"), exporter


# -- import-safety + lazy-export contract (holds regardless of the extra) ----


def test_module_imports_without_opentelemetry() -> None:
    importlib.import_module("promptetheus.adapters.otel")


def test_lazy_export_is_callable() -> None:
    from promptetheus.adapters import OpenTelemetryBridge

    assert callable(OpenTelemetryBridge)


@pytest.mark.skipif(
    _HAS_OTEL,
    reason="opentelemetry installed; this asserts the missing-dependency error path",
)
def test_calling_without_otel_raises_clear_error() -> None:
    from promptetheus.adapters import OpenTelemetryBridge

    with pytest.raises(RuntimeError, match="otel"):
        OpenTelemetryBridge()


# -- real integration against an in-memory OTel tracer ----------------------


@pytest.mark.skipif(
    not _HAS_OTEL_SDK,
    reason="opentelemetry-sdk not installed; skipping real-tracer integration",
)
def test_helpers_emit_real_spans_and_forward_to_session() -> None:
    """Each bridged helper creates a real span and forwards to the session.

    Drives tool_call/tool_result/llm_call through the bridge wired to a real
    in-memory tracer, then asserts: span names equal the Promptetheus event
    types; payload fields land as promptetheus.<key> attributes; the
    session_id correlation attribute is present; and the wrapped session
    recorded the same events (Promptetheus remains the source of truth).
    """
    from promptetheus.adapters import OpenTelemetryBridge

    tracer, exporter = _build_inmemory_tracer()
    transport = RecordingTransport()
    session = Session(agent="acme", user_goal="book a meeting", transport=transport)
    bridge = OpenTelemetryBridge(session=session, tracer=tracer)

    bridge.tool_call("search", {"q": "rooms", "n": 3}, call_id="c1")
    bridge.tool_result("c1", result="ok")
    bridge.llm_call("gpt-4o", input_tokens=11, output_tokens=7, latency_ms=42)

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["tool_call", "tool_result", "llm_call"]

    by_name = {s.name: dict(s.attributes) for s in spans}

    tool_call_attrs = by_name["tool_call"]
    assert tool_call_attrs["promptetheus.tool_name"] == "search"
    assert tool_call_attrs["promptetheus.call_id"] == "c1"
    assert tool_call_attrs["promptetheus.session_id"] == session.session_id
    assert tool_call_attrs["promptetheus.seq"] == 0

    assert by_name["tool_result"]["promptetheus.call_id"] == "c1"
    assert by_name["tool_result"]["promptetheus.result"] == "ok"

    llm_attrs = by_name["llm_call"]
    assert llm_attrs["promptetheus.model"] == "gpt-4o"
    assert llm_attrs["promptetheus.input_tokens"] == 11
    assert llm_attrs["promptetheus.output_tokens"] == 7
    assert llm_attrs["promptetheus.latency_ms"] == 42

    # The wrapped session recorded the same events: Promptetheus is canonical.
    assert [e["type"] for e in transport.events] == [
        "tool_call",
        "tool_result",
        "llm_call",
    ]


@pytest.mark.skipif(
    not _HAS_OTEL_SDK,
    reason="opentelemetry-sdk not installed; skipping real-tracer integration",
)
def test_mirror_reflects_enveloped_event_without_session_emit() -> None:
    """mirror reflects an already-enveloped event onto a span and emits nothing.

    Exercises the correlation fields (session_id/seq/idempotency_key), a
    homogeneous string list kept as a real OTel sequence attribute, a nested
    mapping stringified into a single attribute, and the metadata. mirror must
    not touch the wrapped session.
    """
    from promptetheus.adapters import OpenTelemetryBridge

    tracer, exporter = _build_inmemory_tracer()
    transport = RecordingTransport()
    session = Session(agent="acme", user_goal="goal", transport=transport)
    bridge = OpenTelemetryBridge(session=session, tracer=tracer)

    bridge.mirror(
        {
            "type": "retrieval",
            "session_id": "sess_x",
            "seq": 5,
            "idempotency_key": "sess_x:nonce:5",
            "payload": {
                "query": "rooms",
                "tags": ["a", "b"],
                "nested": {"x": 1},
            },
            "metadata": {"run": "r1"},
        }
    )

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "retrieval"

    attrs = dict(span.attributes)
    assert attrs["promptetheus.session_id"] == "sess_x"
    assert attrs["promptetheus.seq"] == 5
    assert attrs["promptetheus.idempotency_key"] == "sess_x:nonce:5"
    assert attrs["promptetheus.query"] == "rooms"
    # Homogeneous string list survives as a real OTel sequence (a tuple here).
    assert tuple(attrs["promptetheus.tags"]) == ("a", "b")
    # Nested mapping is stringified into one attribute, never deeply expanded.
    assert attrs["promptetheus.nested"] == "{'x': 1}"
    assert attrs["promptetheus.metadata.run"] == "r1"

    # mirror emits nothing on the wrapped session.
    assert transport.events == []


@pytest.mark.skipif(
    not _HAS_OTEL_SDK,
    reason="opentelemetry-sdk not installed; skipping real-tracer integration",
)
def test_bridge_default_tracer_construction_is_safe() -> None:
    """Constructing the bridge without an explicit tracer uses the global provider.

    With no SDK provider installed globally this resolves OTel's no-op tracer,
    which must be harmless: emitting through the bridge neither raises nor stops
    the wrapped session from recording.
    """
    from promptetheus.adapters import OpenTelemetryBridge

    transport = RecordingTransport()
    session = Session(agent="acme", user_goal="goal", transport=transport)
    bridge = OpenTelemetryBridge(session=session)

    bridge.event("state_change", {"name": "custom", "k": "v"})

    assert [e["type"] for e in transport.events] == ["state_change"]


@pytest.mark.skipif(
    not _HAS_OTEL,
    reason="opentelemetry-api not installed; bridge construction requires the extra",
)
def test_wrapped_session_failures_do_not_escape() -> None:
    """Session validation/redactor/custom failures are swallowed by the bridge."""
    from promptetheus.adapters import OpenTelemetryBridge

    class RaisingSession:
        session_id = "boom"

        def event(self, *args: Any, **kwargs: Any) -> None:
            raise ValueError("schema/redactor failure")

    class FakeTracer:
        def start_as_current_span(self, name: str) -> Any:
            raise AssertionError("invalid event should not be mirrored")

    bridge = OpenTelemetryBridge(session=RaisingSession(), tracer=FakeTracer())

    assert bridge.event("not_real", {"x": object()}) == {}
