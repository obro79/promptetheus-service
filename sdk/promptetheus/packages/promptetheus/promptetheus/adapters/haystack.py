"""Haystack 2.x tracing adapter for Promptetheus.

A thin Haystack Tracer that maps Haystack's tracing spans onto the public
Promptetheus Session helpers. Haystack 2.x exposes a tracing protocol under
haystack.tracing: a Tracer with a trace(operation_name, tags=..., parent_span=...)
context manager that yields a Span, plus current_span(). The framework opens a
span around each pipeline run and around each component run, tagging the
component span with its name, type, input, and output. You register a tracer
globally with haystack.tracing.enable_tracing(tracer).

HaystackAdapter is that tracer. Each Haystack span becomes a Promptetheus
run-tree span via Session.span, so the pipeline/component tree shows up as nested
spans in the trace. When a component span closes, the adapter inspects the
component type/name and the standard tags to emit standard events:

- generator / chat-generator components -> llm_call (model, token usage, latency)
- tool-invoking components               -> tool_call + tool_result
- retriever components                   -> retrieval (query + documents)

It introduces no adapter-only event types and no server-side behavior —
everything it emits, a caller could emit by hand with the public session.*
helpers.

haystack is an optional dependency. Importing this module must NOT require
haystack to be installed: the tracing protocol classes are imported lazily,
only when HaystackAdapter is constructed. Without the extra, constructing the
adapter raises a clear RuntimeError naming the haystack extra:

    import haystack.tracing
    from promptetheus.adapters import HaystackAdapter

    haystack.tracing.enable_tracing(HaystackAdapter())   # default session = current()
    pipeline.run(...)

This adapter is REVIEW-ONLY: haystack is not installed in this environment, so
the live Tracer wiring is verified against the documented haystack.tracing.Tracer
protocol and Haystack's standard span tags, not exercised against the library.
Span callbacks log and swallow all telemetry failures, so an instrumentation
problem never raises into Haystack's own pipeline execution path.
"""

from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

from ._base import safe_str

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")

# Standard Haystack span tag keys (lib-verified against Haystack 2.x
# haystack.tracing tags / component tracing). haystack is NOT installed in this
# environment, so these are review-verified against the documented tag names, not
# exercised here.
_TAG_COMPONENT_NAME = "haystack.component.name"
_TAG_COMPONENT_TYPE = "haystack.component.type"
_TAG_COMPONENT_INPUT = "haystack.component.input"
_TAG_COMPONENT_OUTPUT = "haystack.component.output"

# Operation names Haystack uses for its component-level span. The pipeline span
# (haystack.pipeline.run) just brackets the run and maps to a plain Session.span.
_COMPONENT_OPERATION = "haystack.component.run"


def _require_haystack() -> Any:
    """Import and return the Haystack tracing protocol classes, or raise clearly.

    Returns (Tracer, Span) from haystack.tracing. Raised only when
    HaystackAdapter is actually constructed, so importing this module never
    requires the optional haystack extra.
    """
    try:
        from haystack.tracing import Span, Tracer  # noqa: F401

        return Tracer, Span
    except Exception as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(
            "HaystackAdapter requires the optional 'haystack' extra. "
            "Install it with: pip install 'promptetheus[haystack]'"
        ) from exc


def _coerce_int(value: Any) -> int | None:
    """Best-effort int coercion (rejects bool); else None."""
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly
        return None
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_llm_component(component_type: str | None) -> bool:
    """Heuristic: does this component type name denote an LLM call?

    Haystack generator components are named like OpenAIGenerator,
    OpenAIChatGenerator, HuggingFaceLocalGenerator, AzureOpenAIChatGenerator,
    etc. We match the stable "Generator" suffix/substring rather than enumerate
    providers, so new generators are covered.
    """
    if not component_type:
        return False
    return "generator" in component_type.lower()


def _is_retriever_component(component_type: str | None) -> bool:
    """Heuristic: does this component type name denote a retriever?

    Haystack retrievers are named like InMemoryBM25Retriever,
    InMemoryEmbeddingRetriever, etc. — all carry the "Retriever" substring.
    """
    if not component_type:
        return False
    return "retriever" in component_type.lower()


def _is_tool_component(component_type: str | None) -> bool:
    """Heuristic: does this component type name denote a tool invocation?

    Haystack tool execution flows through ToolInvoker (and tool-named
    components). We match the "tool" substring so a tool-invoking component is
    reported as a tool_call/tool_result pair.
    """
    if not component_type:
        return False
    return "tool" in component_type.lower()


def _read_usage(output: Any) -> tuple[int | None, int | None]:
    """Extract (input_tokens, output_tokens) from a generator component output.

    Haystack generators return their metadata under output["meta"] (a list of
    per-reply dicts) where each entry may carry a "usage" mapping with
    prompt_tokens / completion_tokens. We probe the common shapes and return
    only what we can resolve. Never raises.
    """
    try:
        meta = None
        if isinstance(output, dict):
            meta = output.get("meta")
        if meta is None:
            return None, None
        # meta is typically a list of per-reply dicts; also tolerate a bare dict.
        entries = meta if isinstance(meta, list) else [meta]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            usage = entry.get("usage")
            if not isinstance(usage, dict):
                continue
            input_tokens = _coerce_int(
                usage.get("prompt_tokens")
                if usage.get("prompt_tokens") is not None
                else usage.get("input_tokens")
            )
            output_tokens = _coerce_int(
                usage.get("completion_tokens")
                if usage.get("completion_tokens") is not None
                else usage.get("output_tokens")
            )
            if input_tokens is not None or output_tokens is not None:
                return input_tokens, output_tokens
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Promptetheus Haystack adapter failed reading usage", exc_info=True
        )
    return None, None


def _read_model(input_tags: Any, output: Any) -> str:
    """Best-effort model identifier from a generator component's tags.

    Haystack records the component input under haystack.component.input; for a
    generator the model id usually lives there (or in the per-reply meta on the
    output). Falls back to "unknown" so llm_call always has its required model.
    """
    try:
        if isinstance(input_tags, dict):
            for key in ("model", "model_name"):
                model = input_tags.get(key)
                if isinstance(model, str) and model:
                    return model
        if isinstance(output, dict):
            meta = output.get("meta")
            entries = meta if isinstance(meta, list) else [meta] if meta else []
            for entry in entries:
                if isinstance(entry, dict):
                    model = entry.get("model")
                    if isinstance(model, str) and model:
                        return model
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Promptetheus Haystack adapter failed reading model", exc_info=True
        )
    return "unknown"


def _retrieval_documents(output: Any) -> list[dict[str, Any]]:
    """Map a retriever component's output documents to plain dicts.

    Haystack retrievers return output["documents"] as a list of Document
    objects (id, content, score). Mapped to plain dicts so no Haystack types
    leak into the event stream. Never raises.
    """
    documents: list[dict[str, Any]] = []
    try:
        docs = output.get("documents") if isinstance(output, dict) else None
        for doc in docs or []:
            mapped: dict[str, Any] = {}
            doc_id = getattr(doc, "id", None)
            if doc_id is None and isinstance(doc, dict):
                doc_id = doc.get("id")
            if doc_id is not None:
                mapped["id"] = str(doc_id)
            content = getattr(doc, "content", None)
            if content is None and isinstance(doc, dict):
                content = doc.get("content")
            if content is not None:
                mapped["content"] = str(content)
            score = getattr(doc, "score", None)
            if score is None and isinstance(doc, dict):
                score = doc.get("score")
            if score is not None:
                try:
                    mapped["score"] = float(score)
                except (TypeError, ValueError):
                    pass
            documents.append(mapped)
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Promptetheus Haystack adapter failed mapping retrieval documents",
            exc_info=True,
        )
    return documents


def HaystackAdapter(session: "Session | NoopSession | None" = None) -> Any:
    """Build a Haystack Tracer that records to a Promptetheus session.

    Register the result globally with Haystack's tracing:

        import haystack.tracing
        from promptetheus.adapters import HaystackAdapter

        haystack.tracing.enable_tracing(HaystackAdapter())
        pipeline.run(...)

    Args:
        session: The Promptetheus session to record into. Defaults to the
            currently-active session (promptetheus.current), captured at
            tracer-creation time, which yields a no-op session when no session
            is active.

    Returns:
        An instance of a haystack.tracing.Tracer subclass, ready to pass to
        haystack.tracing.enable_tracing.

    Raises:
        RuntimeError: if the optional haystack extra is not installed.
    """
    tracer_cls, span_cls = _require_haystack()

    if session is None:
        from ..session import current

        session = current()

    tracer_session = session

    class _PromptetheusSpan(span_cls):  # type: ignore[misc, valid-type]
        """A Haystack Span backed by a Promptetheus run-tree span.

        Collects tags Haystack sets during the span (component name/type, input,
        output). On close the owning tracer reads these tags to emit the right
        standard Promptetheus event. raw_span returns this object; there is no
        underlying third-party span to expose.
        """

        def __init__(self, operation_name: str, span_id: str | None) -> None:
            self.operation_name = operation_name
            self.promptetheus_span_id = span_id
            self._tags: dict[str, Any] = {}

        def set_tag(self, key: str, value: Any) -> None:
            """Record a single tag (Haystack Span protocol)."""
            try:
                self._tags[key] = value
            except Exception:  # pragma: no cover - defensive
                logger.debug(
                    "Promptetheus Haystack adapter failed set_tag", exc_info=True
                )

        def set_tags(self, tags: dict[str, Any]) -> None:
            """Record several tags at once (Haystack Span protocol)."""
            try:
                if isinstance(tags, dict):
                    self._tags.update(tags)
            except Exception:  # pragma: no cover - defensive
                logger.debug(
                    "Promptetheus Haystack adapter failed set_tags", exc_info=True
                )

        def raw_span(self) -> Any:
            """Return the underlying span object (this span; no third-party span)."""
            return self

        def get_correlation_data_for_logs(self) -> dict[str, Any]:
            """No correlation ids to surface; Promptetheus owns its own ids."""
            return {}

        def tags(self) -> dict[str, Any]:
            return self._tags

    class _PromptetheusTracer(tracer_cls):  # type: ignore[misc, valid-type]
        """Haystack Tracer that mirrors Haystack spans into a Promptetheus session.

        Thin by construction: trace opens a Session.span around the block so
        Haystack's pipeline/component tree nests as Promptetheus run-tree spans;
        component spans additionally emit a standard event on close based on the
        component's tags. Telemetry failures are logged and swallowed, never
        raised into Haystack's pipeline.
        """

        def __init__(self) -> None:
            self.session = tracer_session
            # Context-local stack of spans opened by this tracer. Each async
            # task/thread gets an immutable tuple stack so concurrent pipeline
            # runs never share a mutable list.
            self._span_stack_var: contextvars.ContextVar[
                tuple[_PromptetheusSpan, ...]
            ] = contextvars.ContextVar(
                "promptetheus_haystack_span_stack",
                default=(),
            )

        @contextmanager
        def trace(
            self,
            operation_name: str,
            tags: dict[str, Any] | None = None,
            parent_span: Any | None = None,
        ) -> Iterator[Any]:
            """Open a Promptetheus span mirroring this Haystack span.

            Yields a _PromptetheusSpan that collects Haystack's tags; on exit it
            emits the standard event for a component span. Guarded so a telemetry
            failure never breaks Haystack's pipeline run.
            """
            start = time.monotonic()
            ps = _PromptetheusSpan(operation_name, None)
            if tags:
                ps.set_tags(tags)
            stack = self._span_stack_var.get()
            token = self._span_stack_var.set(stack + (ps,))
            try:
                with self.session.span(operation_name) as span_id:
                    ps.promptetheus_span_id = span_id
                    try:
                        yield ps
                    finally:
                        # Emit the standard event while the component span is
                        # still the active top-of-stack, so the event carries the
                        # component span_id. If this ran after the span closed it
                        # would inherit an outer span_id (or None).
                        self._emit_for_span(ps, start)
            finally:
                self._span_stack_var.reset(token)

        def current_span(self) -> Any | None:
            """Return the innermost active span, or None (Haystack Tracer protocol)."""
            stack = self._span_stack_var.get()
            return stack[-1] if stack else None

        # -- emission ------------------------------------------------------

        def _emit_for_span(self, ps: "_PromptetheusSpan", start: float) -> None:
            """Emit the standard Promptetheus event for a finished component span.

            Pipeline-level spans (and any non-component span) emit nothing beyond
            the Session.span itself. Component spans map to llm_call, tool_call +
            tool_result, or retrieval based on the component type tag. Fully
            guarded.
            """
            try:
                if ps.operation_name != _COMPONENT_OPERATION:
                    return
                tags = ps.tags()
                component_type = safe_str(tags.get(_TAG_COMPONENT_TYPE))
                component_name = safe_str(tags.get(_TAG_COMPONENT_NAME))
                input_tags = tags.get(_TAG_COMPONENT_INPUT)
                output = tags.get(_TAG_COMPONENT_OUTPUT)
                latency_ms = int((time.monotonic() - start) * 1000)

                if _is_llm_component(component_type):
                    self._emit_llm_call(input_tags, output, latency_ms)
                elif _is_retriever_component(component_type):
                    self._emit_retrieval(input_tags, output)
                elif _is_tool_component(component_type):
                    self._emit_tool(component_name, component_type, input_tags, output)
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus Haystack adapter failed emitting span event"
                )

        def _emit_llm_call(self, input_tags: Any, output: Any, latency_ms: int) -> None:
            model = _read_model(input_tags, output)
            input_tokens, output_tokens = _read_usage(output)
            self.session.llm_call(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )

        def _emit_retrieval(self, input_tags: Any, output: Any) -> None:
            query = ""
            if isinstance(input_tags, dict):
                query = safe_str(input_tags.get("query")) or ""
            self.session.retrieval(
                query=query,
                documents=_retrieval_documents(output),
            )

        def _emit_tool(
            self,
            component_name: str | None,
            component_type: str | None,
            input_tags: Any,
            output: Any,
        ) -> None:
            tool_name = component_name or component_type or "tool"
            arguments = input_tags if isinstance(input_tags, dict) else {}
            # A stable call_id pairs this tool_call with its tool_result; the
            # component name is unique within a pipeline run.
            call_id = f"haystack:{tool_name}"
            self.session.tool_call(
                tool_name=tool_name,
                arguments=arguments,
                call_id=call_id,
            )
            self.session.tool_result(
                call_id=call_id,
                result=None if output is None else safe_str(output),
            )

    return _PromptetheusTracer()


__all__ = ["HaystackAdapter"]
