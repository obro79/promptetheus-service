"""OTLP/OpenTelemetry span exporter for Promptetheus (outbound).

This exporter takes a Promptetheus session's event stream and emits it as
OpenTelemetry spans over OTLP, so a team already running an OpenTelemetry stack
can see Promptetheus runs as real spans in their existing tooling. This is the
outbound direction: Promptetheus events are the source of truth and are projected
onto OTel spans. It is distinct from the inbound bridge in adapters/otel.py, which
mirrors live session helper calls one span at a time; this exporter instead takes
a finished event stream and reconstructs the span tree.

How the mapping works. A Promptetheus span is a span_start state_change event and
its matching span_end state_change event, correlated by the span_id envelope
field, with parent linkage given by parent_id. Each such pair becomes one OTel
span. The span name comes from the span_start payload span_name. Duration comes
from a duration_ms payload field when present, otherwise from the gap between the
start and end timestamps. Events that belong to a span but are not span markers
(messages, tool calls, and so on) are projected as span events on their owning
OTel span, with their payload fields copied as prefixed attributes. Top-level
events that carry no span_id are projected onto a single synthetic root span named
after the session so nothing is silently dropped.

Payload fields are copied as span attributes under the promptetheus prefix, the
session_id and seq are attached for correlation, and an error event or a
session_end with a non-ok status marks the owning span's status as error.

The OpenTelemetry SDK and the OTLP/HTTP exporter are optional dependencies. They
are imported lazily through the shared require_extra helper inside methods, so
importing this module never requires the otlp extra. Constructing an exporter that
needs to build its own provider, or calling export, without the extra installed
raises a clear RuntimeError pointing at the promptetheus[otlp] extra.

Usage:

    from promptetheus.exporters import export_session

    export_session(events, endpoint="http://localhost:4318/v1/traces")

or, for advanced use with a provider you already configured:

    from promptetheus.exporters import OTLPExporter

    exporter = OTLPExporter(tracer_provider=my_provider)
    exporter.export(events)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from ..adapters._base import require_extra, safe_str

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Tracer

logger = logging.getLogger("promptetheus")

# Attribute namespace for projected payload fields.
_PREFIX = "promptetheus"

# OTel span attributes must be primitives or homogeneous sequences of them.
# Anything else is coerced to its repr so a complex payload value can never make
# span creation raise.
_PRIMITIVE_TYPES = (bool, int, float, str)


def _otel_trace() -> Any:
    """Return the opentelemetry.trace module, or raise a clear missing-extra error."""
    require_extra("opentelemetry", "otlp", "OTLPExporter")
    from opentelemetry import trace as otel_trace

    return otel_trace


def _attr_value(value: Any) -> Any:
    """Coerce a payload value into an OTel-safe span attribute value.

    OpenTelemetry accepts bool, int, float, str and homogeneous sequences of
    those. Anything else (dicts, objects, mixed sequences) is stringified so
    attribute setting can never raise.
    """
    if isinstance(value, bool) or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        items = list(value)
        if items and all(
            isinstance(item, _PRIMITIVE_TYPES) and not isinstance(item, bool)
            for item in items
        ):
            first_type = type(items[0])
            if all(type(item) is first_type for item in items):
                return list(items)
        return repr(value)
    return repr(value)


def _flatten_attributes(prefix: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a one-level payload into prefixed OTel attributes. Never raises."""
    attributes: dict[str, Any] = {}
    try:
        for key, value in payload.items():
            if value is None:
                continue
            attributes[f"{prefix}.{key}"] = _attr_value(value)
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Promptetheus OTLP exporter failed flattening payload", exc_info=True
        )
    return attributes


def _parse_timestamp_ns(timestamp: Any) -> int | None:
    """Parse an ISO 8601 timestamp string to epoch nanoseconds, or None.

    Promptetheus timestamps are ISO 8601 strings (optionally with a trailing Z).
    Returns None for anything unparseable, so a missing or malformed timestamp
    just means the span falls back to the SDK clock rather than raising.
    """
    text = safe_str(timestamp)
    if text is None:
        return None
    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1_000_000_000)
    except Exception:
        return None


def _is_span_start(event: Mapping[str, Any]) -> bool:
    payload = event.get("payload")
    return (
        event.get("type") == "state_change"
        and isinstance(payload, Mapping)
        and payload.get("name") == "span_start"
    )


def _is_span_end(event: Mapping[str, Any]) -> bool:
    payload = event.get("payload")
    return (
        event.get("type") == "state_change"
        and isinstance(payload, Mapping)
        and payload.get("name") == "span_end"
    )


class _SpanNode:
    """A reconstructed Promptetheus span: its markers, children, and inner events."""

    __slots__ = ("span_id", "parent_id", "name", "start", "end", "events")

    def __init__(self, span_id: str) -> None:
        self.span_id = span_id
        self.parent_id: str | None = None
        self.name: str | None = None
        self.start: Mapping[str, Any] | None = None
        self.end: Mapping[str, Any] | None = None
        # Non-marker events stamped with this span_id, in arrival order.
        self.events: list[Mapping[str, Any]] = []


class OTLPExporter:
    """Project a Promptetheus event stream onto OpenTelemetry spans over OTLP.

    The exporter reconstructs the Promptetheus span tree from a finished event
    stream and emits one OTel span per Promptetheus span, with parent linkage
    preserved. Non-span-marker events are attached as span events on their owning
    span. Errors mark the owning span's status as error.

    Either supply a configured OpenTelemetry TracerProvider, or pass an endpoint
    and let the exporter build a default OTLP/HTTP provider. When neither is given
    the exporter falls back to the globally configured provider via
    opentelemetry.trace.get_tracer, which is the no-op provider when none is set.

    Args:
        tracer_provider: A configured OpenTelemetry TracerProvider to emit spans
            through. Takes precedence over endpoint.
        endpoint: An OTLP/HTTP traces endpoint (for instance
            http://localhost:4318/v1/traces). When given and no tracer_provider is
            supplied, the exporter builds a TracerProvider with a batch OTLP/HTTP
            span exporter pointed at it.
        resource_attributes: Optional resource attributes (for instance
            service.name) attached to the provider the exporter builds. Ignored
            when an explicit tracer_provider is supplied.
        headers: Optional OTLP/HTTP headers (for instance auth) for the built
            exporter. Ignored when an explicit tracer_provider is supplied.

    Raises:
        RuntimeError: when the optional otlp extra is not installed and the
            exporter needs it (building a provider, or emitting spans).
    """

    def __init__(
        self,
        tracer_provider: "TracerProvider | None" = None,
        endpoint: str | None = None,
        resource_attributes: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._resource_attributes = dict(resource_attributes or {})
        self._headers = dict(headers or {})
        self._owns_provider = False

        if tracer_provider is not None:
            self._provider: Any = tracer_provider
        elif endpoint is not None:
            self._provider = self._build_provider(endpoint)
            self._owns_provider = True
        else:
            # Defer to the globally configured provider at tracer-acquire time.
            self._provider = None

    def _build_provider(self, endpoint: str) -> Any:
        """Build a TracerProvider with a batch OTLP/HTTP span exporter.

        Imports the OpenTelemetry SDK and the OTLP/HTTP exporter lazily; raises a
        clear missing-extra RuntimeError when the otlp extra is absent.
        """
        require_extra("opentelemetry.sdk", "otlp", "OTLPExporter")
        require_extra(
            "opentelemetry.exporter.otlp.proto.http.trace_exporter",
            "otlp",
            "OTLPExporter",
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = (
            Resource.create(self._resource_attributes)
            if self._resource_attributes
            else None
        )
        provider = (
            TracerProvider(resource=resource)
            if resource is not None
            else TracerProvider()
        )
        span_exporter = OTLPSpanExporter(
            endpoint=endpoint, headers=self._headers or None
        )
        provider.add_span_processor(BatchSpanProcessor(span_exporter))
        return provider

    def _tracer(self) -> "Tracer":
        """Return the tracer to emit spans through (raises if the extra is absent)."""
        otel_trace = _otel_trace()
        if self._provider is not None:
            return self._provider.get_tracer(_PREFIX)
        return otel_trace.get_tracer(_PREFIX)

    # -- reconstruction ----------------------------------------------------

    @staticmethod
    def _build_tree(
        events: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, _SpanNode], list[Mapping[str, Any]]]:
        """Group events into span nodes; return (nodes_by_id, rootless_events).

        Span markers populate each node's name, parent, and start/end markers.
        Non-marker events stamped with a span_id attach to that node. Events with
        no span_id are returned separately so the caller can place them under a
        synthetic root span.
        """
        nodes: dict[str, _SpanNode] = {}
        rootless: list[Mapping[str, Any]] = []

        def node_for(span_id: str) -> _SpanNode:
            node = nodes.get(span_id)
            if node is None:
                node = _SpanNode(span_id)
                nodes[span_id] = node
            return node

        for event in events:
            if not isinstance(event, Mapping):
                continue
            span_id = safe_str(event.get("span_id"))
            if _is_span_start(event) and span_id is not None:
                node = node_for(span_id)
                node.start = event
                node.parent_id = safe_str(event.get("parent_id"))
                payload = event.get("payload")
                if isinstance(payload, Mapping):
                    node.name = safe_str(payload.get("span_name"))
                continue
            if _is_span_end(event) and span_id is not None:
                node = node_for(span_id)
                node.end = event
                if node.name is None:
                    payload = event.get("payload")
                    if isinstance(payload, Mapping):
                        node.name = safe_str(payload.get("span_name"))
                continue
            if span_id is not None:
                node_for(span_id).events.append(event)
            else:
                rootless.append(event)

        return nodes, rootless

    # -- attribute / status helpers ----------------------------------------

    @staticmethod
    def _event_attributes(event: Mapping[str, Any]) -> dict[str, Any]:
        """Correlation plus payload/metadata attributes for one Promptetheus event."""
        attributes: dict[str, Any] = {}
        session_id = safe_str(event.get("session_id"))
        if session_id is not None:
            attributes[f"{_PREFIX}.session_id"] = session_id
        seq = event.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            attributes[f"{_PREFIX}.seq"] = seq
        idempotency_key = safe_str(event.get("idempotency_key"))
        if idempotency_key is not None:
            attributes[f"{_PREFIX}.idempotency_key"] = idempotency_key
        event_type = safe_str(event.get("type"))
        if event_type is not None:
            attributes[f"{_PREFIX}.event_type"] = event_type

        payload = event.get("payload")
        if isinstance(payload, Mapping):
            attributes.update(_flatten_attributes(_PREFIX, payload))
        metadata = event.get("metadata")
        if isinstance(metadata, Mapping):
            attributes.update(_flatten_attributes(f"{_PREFIX}.metadata", metadata))
        return attributes

    @staticmethod
    def _is_error_event(event: Mapping[str, Any]) -> bool:
        """Whether an inner event should mark its owning span as failed."""
        event_type = event.get("type")
        payload = event.get("payload")
        if event_type == "error":
            return True
        if event_type == "tool_result" and isinstance(payload, Mapping):
            return safe_str(payload.get("error")) is not None
        if event_type == "session_end" and isinstance(payload, Mapping):
            status = safe_str(payload.get("status"))
            return status is not None and status.lower() not in (
                "ok",
                "success",
                "completed",
            )
        if event_type == "goal_check" and isinstance(payload, Mapping):
            return payload.get("passed") is False
        return False

    def _span_times(self, node: _SpanNode) -> tuple[int | None, int | None]:
        """Compute (start_ns, end_ns) for a node from duration_ms or timestamps.

        Prefers an explicit duration_ms on either marker payload (start time plus
        the duration); otherwise uses the start and end marker timestamps as-is.
        Returns None for an endpoint that cannot be determined, letting the SDK
        clock fill it in.
        """
        start_ns = (
            _parse_timestamp_ns(node.start.get("timestamp")) if node.start else None
        )

        duration_ms: Any = None
        for marker in (node.start, node.end):
            if isinstance(marker, Mapping):
                payload = marker.get("payload")
                if (
                    isinstance(payload, Mapping)
                    and payload.get("duration_ms") is not None
                ):
                    duration_ms = payload.get("duration_ms")
                    break

        if (
            start_ns is not None
            and isinstance(duration_ms, (int, float))
            and not isinstance(duration_ms, bool)
        ):
            return start_ns, start_ns + int(duration_ms * 1_000_000)

        end_ns = _parse_timestamp_ns(node.end.get("timestamp")) if node.end else None
        return start_ns, end_ns

    # -- emission ----------------------------------------------------------

    def export(self, events: Iterable[Mapping[str, Any]]) -> int:
        """Project an event stream onto OTel spans. Returns the span count emitted.

        Reconstructs the Promptetheus span tree, emits one OTel span per
        Promptetheus span with parent linkage, attaches non-marker events as span
        events, and marks spans whose inner events include an error as failed.
        Rootless top-level events are gathered under a synthetic session root span.

        Raises RuntimeError when the optional otlp extra is absent.
        """
        event_list = [e for e in events if isinstance(e, Mapping)]
        tracer = self._tracer()
        nodes, rootless = self._build_tree(event_list)

        otel_trace = _otel_trace()
        # Cache the OTel span objects so a child can be opened with its parent in
        # context. Spans are emitted parent-before-child via a stable order.
        emitted: dict[str, Any] = {}
        count = 0

        def depth(node: _SpanNode) -> int:
            d = 0
            seen: set[str] = set()
            current: str | None = node.parent_id
            while current is not None and current in nodes and current not in seen:
                seen.add(current)
                d += 1
                current = nodes[current].parent_id
            return d

        # A synthetic root span gives rootless events a home and a stable parent
        # for top-level Promptetheus spans, keeping one tree per session.
        session_id = self._session_id(event_list)
        root_name = (
            f"promptetheus.session {session_id}"
            if session_id
            else "promptetheus.session"
        )
        root_attrs: dict[str, Any] = {}
        if session_id:
            root_attrs[f"{_PREFIX}.session_id"] = session_id

        root_span = tracer.start_span(root_name)
        _set_attributes(root_span, root_attrs)
        count += 1
        root_ctx = otel_trace.set_span_in_context(root_span)
        root_error = False

        try:
            for event in rootless:
                self._add_event(root_span, event)
                if self._is_error_event(event):
                    root_error = True

            for node in sorted(nodes.values(), key=depth):
                parent_span = emitted.get(node.parent_id) if node.parent_id else None
                parent_ctx = (
                    otel_trace.set_span_in_context(parent_span)
                    if parent_span is not None
                    else root_ctx
                )
                start_ns, end_ns = self._span_times(node)
                name = node.name or "span"
                span = tracer.start_span(name, context=parent_ctx, start_time=start_ns)
                emitted[node.span_id] = span
                count += 1

                span_attrs: dict[str, Any] = {f"{_PREFIX}.span_id": node.span_id}
                if node.parent_id:
                    span_attrs[f"{_PREFIX}.parent_id"] = node.parent_id
                if session_id:
                    span_attrs[f"{_PREFIX}.session_id"] = session_id
                if node.start is not None:
                    start_payload = node.start.get("payload")
                    if isinstance(start_payload, Mapping):
                        span_attrs.update(
                            _flatten_attributes(f"{_PREFIX}.span", start_payload)
                        )
                _set_attributes(span, span_attrs)

                node_error = False
                for inner in node.events:
                    self._add_event(span, inner)
                    if self._is_error_event(inner):
                        node_error = True
                if node_error:
                    self._mark_error(span)

                self._end_span(span, end_ns)

            if root_error:
                self._mark_error(root_span)
        finally:
            self._end_span(root_span, None)

        return count

    def _add_event(self, span: Any, event: Mapping[str, Any]) -> None:
        """Attach a Promptetheus event as a named OTel span event. Never raises."""
        try:
            name = safe_str(event.get("type")) or "event"
            timestamp_ns = _parse_timestamp_ns(event.get("timestamp"))
            attributes = self._event_attributes(event)
            if timestamp_ns is not None:
                span.add_event(name, attributes=attributes, timestamp=timestamp_ns)
            else:
                span.add_event(name, attributes=attributes)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Promptetheus OTLP exporter skipped span event", exc_info=True)

    def _mark_error(self, span: Any) -> None:
        """Set a span's status to error. Never raises.

        Status and StatusCode are reached through the same _otel_trace accessor
        every other opentelemetry use goes through, so all opentelemetry access
        routes through one lazy point (and one patch point in tests).
        """
        try:
            otel_trace = _otel_trace()
            span.set_status(otel_trace.Status(otel_trace.StatusCode.ERROR))
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "Promptetheus OTLP exporter could not set error status", exc_info=True
            )

    @staticmethod
    def _end_span(span: Any, end_ns: int | None) -> None:
        """End a span at end_ns when known, else at the SDK clock. Never raises."""
        try:
            if end_ns is not None:
                span.end(end_time=end_ns)
            else:
                span.end()
        except Exception:  # pragma: no cover - defensive
            logger.debug("Promptetheus OTLP exporter failed ending span", exc_info=True)

    @staticmethod
    def _session_id(events: Sequence[Mapping[str, Any]]) -> str | None:
        for event in events:
            session_id = safe_str(event.get("session_id"))
            if session_id is not None:
                return session_id
        return None


def export_session(
    events: Iterable[Mapping[str, Any]],
    endpoint: str | None = None,
    tracer_provider: "TracerProvider | None" = None,
    resource_attributes: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> int:
    """Export a Promptetheus event stream as OpenTelemetry spans in one call.

    Convenience wrapper around OTLPExporter for the common case: build an exporter
    from an endpoint (or an explicit provider) and project the events. Returns the
    number of OTel spans emitted. Raises RuntimeError when the optional otlp extra
    is absent.
    """
    exporter = OTLPExporter(
        tracer_provider=tracer_provider,
        endpoint=endpoint,
        resource_attributes=resource_attributes,
        headers=headers,
    )
    return exporter.export(events)


def _set_attributes(span: Any, attributes: Mapping[str, Any]) -> None:
    """Set span attributes one at a time, skipping any that OTel rejects.

    Setting attributes individually means one bad value cannot drop the rest; any
    rejection is logged at debug and skipped. Never raises.
    """
    for key, value in attributes.items():
        try:
            span.set_attribute(key, value)
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "Promptetheus OTLP exporter skipped attribute %r", key, exc_info=True
            )


__all__ = ["OTLPExporter", "export_session"]
