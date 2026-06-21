"""Tests for the outbound OTLP/OpenTelemetry span exporter.

Two layers of coverage:

- The event-to-span mapping logic is exercised with a fake tracer that records
  span operations, so the core reconstruction and projection are covered even when
  the real OpenTelemetry libraries are not installed. The exporter only touches
  opentelemetry lazily, so a fake tracer_provider keeps every import out of the way
  except a couple of trace helper lookups, which are guarded.

- A thin smoke test that uses the real in-memory OpenTelemetry SDK is skipped
  cleanly when opentelemetry is absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.exporters import otlp as otlp_mod  # noqa: E402
from promptetheus.exporters.otlp import OTLPExporter, export_session  # noqa: E402
from promptetheus.session import Session  # noqa: E402


# -- fakes -----------------------------------------------------------------


class FakeSpan:
    def __init__(self, name, context=None, start_time=None):
        self.name = name
        self.context = context
        self.start_time = start_time
        self.end_time = "unset"
        self.attributes = {}
        self.events = []  # list of (name, attributes, timestamp)
        self.status = None
        self.ended = False

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def add_event(self, name, attributes=None, timestamp=None):
        self.events.append((name, dict(attributes or {}), timestamp))

    def set_status(self, status):
        self.status = status

    def end(self, end_time=None):
        self.ended = True
        self.end_time = end_time


class FakeTracer:
    def __init__(self):
        self.spans = []

    def start_span(self, name, context=None, start_time=None):
        span = FakeSpan(name, context=context, start_time=start_time)
        self.spans.append(span)
        return span


class FakeProvider:
    def __init__(self):
        self.tracer = FakeTracer()

    def get_tracer(self, name):
        return self.tracer


# -- event-stream builders -------------------------------------------------


class RecordingTransport:
    def __init__(self):
        self.events = []

    def send_event(self, event):
        self.events.append(event)

    def flush(self, timeout=None):
        pass


def _stream_with_spans():
    transport = RecordingTransport()
    session = Session(agent="a", user_goal="g", session_id="s1", transport=transport)
    session.user_message("top level message")
    with session.span("outer"):
        session.agent_message("in outer")
        with session.span("inner"):
            session.tool_call("search", {"q": "rooms"}, call_id="c1")
            session.tool_result("c1", error="boom")
    return transport.events


def _patch_status(monkeypatch):
    """Make _mark_error usable without the real opentelemetry by faking Status/StatusCode.

    The exporter imports Status and StatusCode lazily inside _mark_error; provide a
    tiny fake opentelemetry.trace module so the import resolves without the libs.
    """
    import types

    fake_trace = types.ModuleType("opentelemetry.trace")

    class StatusCode:
        ERROR = "ERROR"

    class Status:
        def __init__(self, code):
            self.code = code

    fake_trace.Status = Status
    fake_trace.StatusCode = StatusCode

    def set_span_in_context(span, context=None):
        return ("ctx", span)

    fake_trace.set_span_in_context = set_span_in_context

    def fake_otel_trace():
        return fake_trace

    monkeypatch.setattr(otlp_mod, "_otel_trace", fake_otel_trace)
    return fake_trace


# -- mapping logic tests (no real OTel needed) -----------------------------


def test_event_to_span_mapping_with_fake_tracer(monkeypatch):
    _patch_status(monkeypatch)
    provider = FakeProvider()
    events = _stream_with_spans()

    count = export_session(events, tracer_provider=provider)

    spans = provider.tracer.spans
    # One synthetic root + outer + inner = 3 spans.
    assert count == 3
    assert len(spans) == 3

    root = spans[0]
    assert root.name.startswith("promptetheus.session")
    assert root.attributes["promptetheus.session_id"] == "s1"

    by_name = {s.name: s for s in spans}
    assert "outer" in by_name and "inner" in by_name
    outer, inner = by_name["outer"], by_name["inner"]

    # Both Promptetheus spans carry their own span_id as an attribute.
    assert outer.attributes["promptetheus.span_id"]
    assert inner.attributes["promptetheus.span_id"]


def test_top_level_span_has_no_promptetheus_parent_and_inner_links_to_outer(monkeypatch):
    _patch_status(monkeypatch)
    provider = FakeProvider()
    events = _stream_with_spans()
    export_session(events, tracer_provider=provider)

    by_name = {s.name: s for s in provider.tracer.spans if not s.name.startswith("promptetheus.session")}
    outer, inner = by_name["outer"], by_name["inner"]

    # Outer is a top-level Promptetheus span: no promptetheus.parent_id attribute.
    assert "promptetheus.parent_id" not in outer.attributes
    # Inner's parent_id attribute equals outer's span_id.
    assert inner.attributes["promptetheus.parent_id"] == outer.attributes["promptetheus.span_id"]


def test_inner_events_attached_and_error_marks_status(monkeypatch):
    _patch_status(monkeypatch)
    provider = FakeProvider()
    events = _stream_with_spans()
    export_session(events, tracer_provider=provider)

    by_name = {s.name: s for s in provider.tracer.spans}
    inner = by_name["inner"]

    inner_event_names = [name for name, _attrs, _ts in inner.events]
    assert "tool_call" in inner_event_names
    assert "tool_result" in inner_event_names

    # tool_call payload fields are copied as prefixed attributes on the span event.
    tool_call_event = [e for e in inner.events if e[0] == "tool_call"][0]
    assert tool_call_event[1]["promptetheus.tool_name"] == "search"

    # The tool_result carried an error string, so the inner span is marked error.
    # _mark_error reaches Status/StatusCode through the same _otel_trace accessor
    # that _patch_status fakes, so this path is exercised even with no real
    # opentelemetry installed. The fake Status exposes code; a real one exposes
    # status_code. Accept either shape.
    assert inner.status is not None
    status_code = getattr(inner.status, "status_code", None) or getattr(
        inner.status, "code", None
    )
    assert str(status_code).endswith("ERROR")


def test_rootless_top_level_events_land_on_synthetic_root(monkeypatch):
    _patch_status(monkeypatch)
    provider = FakeProvider()
    events = _stream_with_spans()
    export_session(events, tracer_provider=provider)

    root = provider.tracer.spans[0]
    root_event_names = [name for name, _attrs, _ts in root.events]
    # The top-level user_message (no span_id) lands on the synthetic root span.
    assert "user_message" in root_event_names


def test_duration_ms_drives_span_end(monkeypatch):
    _patch_status(monkeypatch)
    provider = FakeProvider()

    # Hand-built minimal span pair carrying an explicit duration_ms.
    start_ts = "2026-06-15T00:00:00+00:00"
    events = [
        {
            "type": "state_change",
            "session_id": "s9",
            "timestamp": start_ts,
            "seq": 0,
            "idempotency_key": "k0",
            "payload": {"name": "span_start", "span_name": "work", "duration_ms": 250},
            "span_id": "sp1",
            "parent_id": None,
        },
        {
            "type": "state_change",
            "session_id": "s9",
            "timestamp": "2026-06-15T00:00:05+00:00",
            "seq": 1,
            "idempotency_key": "k1",
            "payload": {"name": "span_end", "span_name": "work"},
            "span_id": "sp1",
            "parent_id": None,
        },
    ]

    export_session(events, tracer_provider=provider)
    work = [s for s in provider.tracer.spans if s.name == "work"][0]
    # start + 250ms (not the 5s implied by the end timestamp).
    assert work.end_time == work.start_time + 250 * 1_000_000


def test_export_returns_span_count_and_ends_all(monkeypatch):
    _patch_status(monkeypatch)
    provider = FakeProvider()
    events = _stream_with_spans()
    count = export_session(events, tracer_provider=provider)
    assert count == len(provider.tracer.spans)
    assert all(s.ended for s in provider.tracer.spans)


def test_module_imports_without_otel_extra():
    # Importing the exporter must never require the extra. Building an exporter
    # with no endpoint and no provider also must not import anything; only
    # export() / _tracer() reach for opentelemetry.
    exporter = OTLPExporter()
    assert exporter is not None


# -- real-OTel smoke test (skips cleanly without the libs) -----------------


def test_real_otel_sdk_roundtrip():
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = TracerProvider()
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))

    events = _stream_with_spans()
    count = OTLPExporter(tracer_provider=provider).export(events)

    finished = memory.get_finished_spans()
    assert count == len(finished)
    names = {s.name for s in finished}
    assert "outer" in names and "inner" in names
