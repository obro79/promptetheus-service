"""Tests for the Haystack 2.x tracing adapter.

Two layers:

- Import-safety + lazy-error contract, which holds whether or not haystack is
  installed: importing promptetheus.adapters.haystack never requires the
  extra, the public HaystackAdapter factory is lazily exported and callable, and
  constructing it without the extra raises a clear RuntimeError mentioning the
  haystack extra.
- Behavioral mock integration: haystack is NOT installed in this environment, so
  this adapter is REVIEW-ONLY against the documented haystack.tracing.Tracer
  protocol. To still exercise the mapping logic, the behavioral test injects a
  stand-in haystack.tracing module (matching the documented Tracer/Span
  protocol) into sys.modules, builds the adapter against it, and drives it the
  way Haystack drives a registered tracer: opening a pipeline span and component
  spans (tagged with the standard haystack.component.* tags) and asserting the
  adapter emits only public Promptetheus events (llm_call / tool_call /
  tool_result / retrieval) nested under run-tree spans.
"""

from __future__ import annotations

import contextlib
import contextvars
import importlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Iterator

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.session import Session  # noqa: E402

_HAS_HAYSTACK = importlib.util.find_spec("haystack") is not None

# Event types the Haystack adapter is permitted to emit. state_change is allowed
# because Session.span emits span_start/span_end state_change events; anything
# else outside this set means the adapter grew an adapter-only event type, which
# violates "adapters stay thin".
PUBLIC_ADAPTER_EVENT_TYPES = {
    "llm_call",
    "tool_call",
    "tool_result",
    "retrieval",
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


def test_module_imports_without_haystack() -> None:
    # Importing the adapter module must not require haystack.
    importlib.import_module("promptetheus.adapters.haystack")


def test_lazy_export_is_callable() -> None:
    from promptetheus.adapters import HaystackAdapter

    assert callable(HaystackAdapter)


@pytest.mark.skipif(
    _HAS_HAYSTACK,
    reason="haystack installed; this asserts the missing-dependency error path",
)
def test_calling_without_haystack_raises_clear_error() -> None:
    from promptetheus.adapters import HaystackAdapter

    with pytest.raises(RuntimeError, match="haystack"):
        HaystackAdapter()


# -- behavioral mock integration (haystack stand-in injected into sys.modules) --


@contextlib.contextmanager
def _fake_haystack_tracing() -> Iterator[None]:
    """Install a stand-in haystack.tracing module matching the documented protocol.

    Haystack 2.x's haystack.tracing exposes abstract Tracer and Span base
    classes. The real library is not installed here, so we register minimal
    stand-ins with the documented method surface (Tracer.trace / current_span;
    Span.set_tag / set_tags / raw_span / get_correlation_data_for_logs). The
    adapter subclasses these, so this lets us drive the documented protocol
    without the dependency, then restores sys.modules afterward.
    """

    class Span:
        def set_tag(self, key: str, value: Any) -> None:  # pragma: no cover - overridden
            raise NotImplementedError

        def set_tags(self, tags: dict[str, Any]) -> None:
            for key, value in tags.items():
                self.set_tag(key, value)

        def raw_span(self) -> Any:  # pragma: no cover - overridden
            raise NotImplementedError

        def get_correlation_data_for_logs(self) -> dict[str, Any]:
            return {}

    class Tracer:
        def trace(
            self,
            operation_name: str,
            tags: dict[str, Any] | None = None,
            parent_span: Any | None = None,
        ) -> Any:  # pragma: no cover - overridden
            raise NotImplementedError

        def current_span(self) -> Any:  # pragma: no cover - overridden
            raise NotImplementedError

    haystack_pkg = types.ModuleType("haystack")
    tracing_mod = types.ModuleType("haystack.tracing")
    tracing_mod.Tracer = Tracer  # type: ignore[attr-defined]
    tracing_mod.Span = Span  # type: ignore[attr-defined]
    haystack_pkg.tracing = tracing_mod  # type: ignore[attr-defined]

    saved = {
        name: sys.modules.get(name)
        for name in ("haystack", "haystack.tracing", "promptetheus.adapters.haystack")
    }
    sys.modules["haystack"] = haystack_pkg
    sys.modules["haystack.tracing"] = tracing_mod
    # Drop a cached adapter module so its lazy import binds to the stand-in.
    sys.modules.pop("promptetheus.adapters.haystack", None)
    try:
        yield
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def test_adapter_is_a_haystack_tracer_and_emits_public_events() -> None:
    """Driving the adapter as a Haystack tracer emits only public events.

    Mirrors how Haystack drives a registered tracer: a pipeline span wrapping
    component spans, each component span tagged with the standard
    haystack.component.* tags. The adapter must open nested Session spans and emit
    llm_call / tool_call+tool_result / retrieval based on component type, and
    never raise into the trace context.
    """
    with _fake_haystack_tracing():
        haystack_adapter = importlib.import_module("promptetheus.adapters.haystack")
        import haystack.tracing as haystack_tracing

        transport = RecordingTransport()
        session = Session(agent="agent", user_goal="goal", transport=transport)
        tracer = haystack_adapter.HaystackAdapter(session)

        # The adapter is a genuine haystack.tracing.Tracer subclass.
        assert isinstance(tracer, haystack_tracing.Tracer)

        # -- Haystack opens the pipeline span, then a component span per node.
        with tracer.trace("haystack.pipeline.run") as pipeline_span:
            # current_span must surface the innermost active span (Haystack relies
            # on this to attach tags / nest spans).
            assert tracer.current_span() is pipeline_span

            # Generator component -> llm_call (model from input, usage from output).
            with tracer.trace("haystack.component.run") as gen_span:
                assert tracer.current_span() is gen_span
                gen_span.set_tags(
                    {
                        "haystack.component.name": "llm",
                        "haystack.component.type": "OpenAIChatGenerator",
                        "haystack.component.input": {"model": "gpt-4o-mini"},
                        "haystack.component.output": {
                            "replies": ["hi"],
                            "meta": [
                                {
                                    "model": "gpt-4o-mini",
                                    "usage": {
                                        "prompt_tokens": 12,
                                        "completion_tokens": 5,
                                    },
                                }
                            ],
                        },
                    }
                )

            # Retriever component -> retrieval (query + mapped documents).
            class _Doc:
                def __init__(self, doc_id: str, content: str, score: float) -> None:
                    self.id = doc_id
                    self.content = content
                    self.score = score

            with tracer.trace("haystack.component.run") as ret_span:
                ret_span.set_tag("haystack.component.name", "retriever")
                ret_span.set_tag("haystack.component.type", "InMemoryBM25Retriever")
                ret_span.set_tag("haystack.component.input", {"query": "rooms"})
                ret_span.set_tag(
                    "haystack.component.output",
                    {"documents": [_Doc("n1", "doc text", 0.9)]},
                )

            # Tool-invoking component -> tool_call + tool_result.
            with tracer.trace("haystack.component.run") as tool_span:
                tool_span.set_tags(
                    {
                        "haystack.component.name": "search",
                        "haystack.component.type": "ToolInvoker",
                        "haystack.component.input": {"query": "rooms"},
                        "haystack.component.output": "found 3",
                    }
                )

        # After the whole tree closes, the stack drains back to empty.
        assert tracer.current_span() is None

        # Only public event types (plus span state_changes) were emitted.
        emitted_types = {e["type"] for e in transport.events}
        assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

        # llm_call carries model, mapped usage, and a latency; no raw prompt.
        llm_calls = _events_of(transport, "llm_call")
        assert len(llm_calls) == 1
        llm_payload = llm_calls[0]["payload"]
        assert llm_payload["model"] == "gpt-4o-mini"
        assert llm_payload["input_tokens"] == 12
        assert llm_payload["output_tokens"] == 5
        assert "latency_ms" in llm_payload
        # It nests under the component span (which nests under the pipeline span).
        assert "span_id" in llm_calls[0]

        # retrieval maps Document objects to plain dicts.
        retrievals = _events_of(transport, "retrieval")
        assert len(retrievals) == 1
        ret_payload = retrievals[0]["payload"]
        assert ret_payload["query"] == "rooms"
        assert ret_payload["documents"] == [
            {"id": "n1", "content": "doc text", "score": 0.9}
        ]

        # tool_call + tool_result correlate by a stable component-derived call_id.
        tool_calls = _events_of(transport, "tool_call")
        tool_results = _events_of(transport, "tool_result")
        assert len(tool_calls) == 1
        assert len(tool_results) == 1
        assert tool_calls[0]["payload"]["tool_name"] == "search"
        assert tool_calls[0]["payload"]["call_id"] == tool_results[0]["payload"]["call_id"]
        assert tool_results[0]["payload"]["result"] == "found 3"

        # Pipeline-level span emitted no standard event of its own (only spans).
        span_changes = _events_of(transport, "state_change")
        span_starts = [e for e in span_changes if e["payload"].get("name") == "span_start"]
        # One pipeline span + three component spans.
        assert len(span_starts) == 4


def test_component_event_carries_its_own_span_id_without_enclosing_pipeline() -> None:
    """A lone component span emits its event stamped with that component span_id.

    Regression for the span-nesting defect: the standard event must be emitted
    while the component span is the active top-of-stack, not after it closes.
    With no enclosing pipeline span, the emitted llm_call must carry the
    component span's own span_id (the span_start state_change's span_id), never
    None.
    """
    with _fake_haystack_tracing():
        haystack_adapter = importlib.import_module("promptetheus.adapters.haystack")

        transport = RecordingTransport()
        session = Session(agent="agent", user_goal="goal", transport=transport)
        tracer = haystack_adapter.HaystackAdapter(session)

        # A single component span, with no enclosing pipeline span.
        with tracer.trace("haystack.component.run") as gen_span:
            gen_span.set_tags(
                {
                    "haystack.component.name": "llm",
                    "haystack.component.type": "OpenAIChatGenerator",
                    "haystack.component.input": {"model": "gpt-4o-mini"},
                    "haystack.component.output": {"meta": []},
                }
            )

        llm_calls = _events_of(transport, "llm_call")
        assert len(llm_calls) == 1
        component_span_id = llm_calls[0].get("span_id")
        assert component_span_id is not None

        # The span_id matches the component span's own span_start, and the event
        # is top-level within that span (no enclosing pipeline span as parent).
        span_starts = [
            e
            for e in _events_of(transport, "state_change")
            if e["payload"].get("name") == "span_start"
        ]
        assert len(span_starts) == 1
        assert span_starts[0]["span_id"] == component_span_id
        assert llm_calls[0].get("parent_id") is None


def test_span_stack_is_context_local_for_concurrent_runs() -> None:
    """Independent contexts must not share Haystack current_span state."""
    with _fake_haystack_tracing():
        haystack_adapter = importlib.import_module("promptetheus.adapters.haystack")

        transport = RecordingTransport()
        session = Session(agent="agent", user_goal="goal", transport=transport)
        tracer = haystack_adapter.HaystackAdapter(session)

        ctx_a = contextvars.copy_context()
        ctx_b = contextvars.copy_context()
        cm_a = tracer.trace("haystack.pipeline.run")
        span_a = ctx_a.run(cm_a.__enter__)
        cm_b = tracer.trace("haystack.pipeline.run")
        span_b = ctx_b.run(cm_b.__enter__)

        try:
            assert span_a is not span_b
            assert tracer.current_span() is None
            assert ctx_a.run(tracer.current_span) is span_a
            assert ctx_b.run(tracer.current_span) is span_b
        finally:
            ctx_b.run(cm_b.__exit__, None, None, None)
            assert ctx_b.run(tracer.current_span) is None
            assert ctx_a.run(tracer.current_span) is span_a
            ctx_a.run(cm_a.__exit__, None, None, None)

        assert ctx_a.run(tracer.current_span) is None


def test_span_callbacks_never_raise_into_haystack() -> None:
    """A telemetry failure inside the span path is swallowed, not raised.

    Haystack must never see an exception from the tracer. We force the session's
    event emission to raise and confirm the trace context still completes.
    """
    with _fake_haystack_tracing():
        haystack_adapter = importlib.import_module("promptetheus.adapters.haystack")

        class _BoomSession:
            session_id = "boom"

            @contextlib.contextmanager
            def span(self, name: str, metadata: Any = None) -> Iterator[None]:
                yield None

            def llm_call(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("telemetry down")

            def tool_call(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("telemetry down")

            def tool_result(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("telemetry down")

            def retrieval(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("telemetry down")

        tracer = haystack_adapter.HaystackAdapter(_BoomSession())

        # Must not raise even though emission blows up on close.
        with tracer.trace("haystack.component.run") as span:
            span.set_tags(
                {
                    "haystack.component.type": "OpenAIGenerator",
                    "haystack.component.input": {"model": "m"},
                    "haystack.component.output": {"meta": []},
                }
            )
        assert tracer.current_span() is None


# -- lib-verified contract against the REAL haystack package -----------------
#
# These run only when haystack is actually installed. They import the real
# haystack.tracing.Tracer/Span and assert the adapter is a genuine Tracer
# subclass, then drive it the way Haystack drives a registered tracer (a
# pipeline span wrapping component spans tagged with the standard
# haystack.component.* tags) and assert it emits only public Promptetheus
# events. With haystack absent they skip, leaving the injected-stand-in
# behavioral coverage above as the portable contract.


@pytest.mark.skipif(
    not _HAS_HAYSTACK,
    reason="haystack not installed; lib-verified path requires the real package",
)
def test_lib_adapter_is_real_haystack_tracer_and_emits_public_events() -> None:
    """Driving the adapter as a real haystack.tracing.Tracer emits only public events."""
    import haystack.tracing as haystack_tracing

    from promptetheus.adapters import HaystackAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    tracer = HaystackAdapter(session)

    # The adapter is a genuine haystack.tracing.Tracer subclass.
    assert isinstance(tracer, haystack_tracing.Tracer)

    class _Doc:
        def __init__(self, doc_id: str, content: str, score: float) -> None:
            self.id = doc_id
            self.content = content
            self.score = score

    with tracer.trace("haystack.pipeline.run") as pipeline_span:
        assert tracer.current_span() is pipeline_span

        with tracer.trace("haystack.component.run") as gen_span:
            assert tracer.current_span() is gen_span
            gen_span.set_tags(
                {
                    "haystack.component.name": "llm",
                    "haystack.component.type": "OpenAIChatGenerator",
                    "haystack.component.input": {"model": "gpt-4o-mini"},
                    "haystack.component.output": {
                        "replies": ["hi"],
                        "meta": [
                            {
                                "model": "gpt-4o-mini",
                                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
                            }
                        ],
                    },
                }
            )

        with tracer.trace("haystack.component.run") as ret_span:
            ret_span.set_tag("haystack.component.name", "retriever")
            ret_span.set_tag("haystack.component.type", "InMemoryBM25Retriever")
            ret_span.set_tag("haystack.component.input", {"query": "rooms"})
            ret_span.set_tag(
                "haystack.component.output",
                {"documents": [_Doc("n1", "doc text", 0.9)]},
            )

        with tracer.trace("haystack.component.run") as tool_span:
            tool_span.set_tags(
                {
                    "haystack.component.name": "search",
                    "haystack.component.type": "ToolInvoker",
                    "haystack.component.input": {"query": "rooms"},
                    "haystack.component.output": "found 3",
                }
            )

    # After the whole tree closes, the stack drains back to empty.
    assert tracer.current_span() is None

    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    llm_calls = _events_of(transport, "llm_call")
    assert len(llm_calls) == 1
    llm_payload = llm_calls[0]["payload"]
    assert llm_payload["model"] == "gpt-4o-mini"
    assert llm_payload["input_tokens"] == 12
    assert llm_payload["output_tokens"] == 5
    assert "span_id" in llm_calls[0]

    retrievals = _events_of(transport, "retrieval")
    assert len(retrievals) == 1
    assert retrievals[0]["payload"]["query"] == "rooms"
    assert retrievals[0]["payload"]["documents"] == [
        {"id": "n1", "content": "doc text", "score": 0.9}
    ]

    tool_calls = _events_of(transport, "tool_call")
    tool_results = _events_of(transport, "tool_result")
    assert len(tool_calls) == 1
    assert len(tool_results) == 1
    assert tool_calls[0]["payload"]["tool_name"] == "search"
    assert tool_calls[0]["payload"]["call_id"] == tool_results[0]["payload"]["call_id"]
    assert tool_results[0]["payload"]["result"] == "found 3"
