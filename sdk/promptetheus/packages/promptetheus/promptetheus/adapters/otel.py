"""OpenTelemetry export bridge for Promptetheus.

A thin bridge that mirrors Promptetheus session events as OpenTelemetry spans, so
a team that already runs an OpenTelemetry stack sees Promptetheus traces in their
existing tooling. This is an *export* direction only: Promptetheus events are the
source of truth, and each event is reflected onto a short-lived OTel span (event
type -> span name, event payload -> span attributes, session_id ->
correlation attribute). It introduces no adapter-only event types and no
server-side behavior — everything that reaches the Promptetheus event stream
still goes through the public Session helpers, and
a caller could emit the same events by hand.

opentelemetry (the opentelemetry-api package, optionally
opentelemetry-sdk) is an optional dependency. Importing this module must NOT
require it — the import is performed *lazily* inside
OpenTelemetryBridge.__init__, so merely importing this module never
needs the extra. Constructing or using the bridge without OpenTelemetry installed
raises a clear RuntimeError pointing at the promptetheus[otel] extra.

Usage — route events through the bridge instead of (or in addition to) the bare
session. The bridge mirrors the bridged helpers it offers onto OTel spans and
forwards to the wrapped session, so it is a drop-in for the subset of
Session helpers it covers:

    from promptetheus import trace
    from promptetheus.adapters import OpenTelemetryBridge

    with trace.start(agent="acme", user_goal="book a meeting") as session:
        otel = OpenTelemetryBridge(session=session)
        otel.tool_call("search", {"q": "rooms"}, call_id="c1")
        otel.tool_result("c1", result="ok")

Already-enveloped Promptetheus events (e.g. from a transport tap) can be mirrored
directly with OpenTelemetryBridge.mirror:

    otel.mirror(event_dict)  # event type -> span name, payload -> attributes

By design the bridge installs no hook inside Session itself; the user routes
events through it at the adapter level. As with every Promptetheus adapter,
mirroring is best-effort: span creation failures are logged and swallowed, never
raised into the caller.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Mapping

from ._base import require_extra

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from opentelemetry.trace import Tracer

    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")

# OTel span attributes must be primitives (or homogeneous sequences of them).
# Anything else is coerced to its repr so a complex payload value can never
# make span creation raise.
_PRIMITIVE_TYPES = (bool, int, float, str)


def _require_opentelemetry() -> Any:
    """Import and return the opentelemetry.trace module or raise clearly.

    Raised only when the bridge is actually constructed, so importing this module
    never requires the optional otel extra. Delegates to the shared require_extra
    helper, which raises the same clear missing-extra error naming the otel extra.
    """
    return require_extra("opentelemetry.trace", "otel", "OpenTelemetryBridge")


def _attr_value(value: Any) -> Any:
    """Coerce a payload value into an OTel-safe span attribute value.

    OpenTelemetry accepts bool/int/float/str and homogeneous
    sequences of those. Anything else (dicts, objects, mixed sequences) is
    stringified so attribute setting can never raise.
    """
    if isinstance(value, bool) or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        items = list(value)
        if items and all(
            isinstance(item, _PRIMITIVE_TYPES) and not isinstance(item, bool)
            for item in items
        ):
            # Homogeneous numeric/str sequence: only safe if a single primitive
            # type is present (OTel requires homogeneity); otherwise stringify.
            first_type = type(items[0])
            if all(type(item) is first_type for item in items):
                return list(items)
        return repr(value)
    return repr(value)


def _flatten_attributes(prefix: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a one-level event payload into prefixed OTel span attributes.

    Nested mappings are stringified (kept as a single attribute) rather than
    deeply expanded — the bridge favors a faithful, minimal mapping over a rich
    one. Never raises.
    """
    attributes: dict[str, Any] = {}
    try:
        for key, value in payload.items():
            if value is None:
                continue
            attributes[f"{prefix}.{key}"] = _attr_value(value)
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Promptetheus OTel bridge failed flattening payload", exc_info=True
        )
    return attributes


class OpenTelemetryBridge:
    """Mirror Promptetheus session events onto OpenTelemetry spans (export).

    The bridge wraps a Promptetheus Session and an
    OpenTelemetry Tracer. For each event routed through it, the bridge emits
    the event on the wrapped session (so Promptetheus stays the source of truth)
    and reflects it onto a short-lived OTel span named after the event type, with
    the payload flattened into promptetheus.<key> span attributes and the
    session_id attached for trace correlation.

    The bridge deliberately installs no hook inside Session; events reach it
    only because the caller routes them through the bridge's helper methods (a
    thin superset-compatible subset of the Session API) or calls
    mirror with an already-enveloped event. This keeps the bridge an
    adapter-level concern with no shared session state.

    Args:
        session: The Promptetheus session to forward events to. Defaults to the
            currently-active session (promptetheus.current), captured at
            construction time (a no-op session when none is active).
        tracer: An OpenTelemetry Tracer. Defaults to a tracer obtained from
            the globally-configured provider via
            opentelemetry.trace.get_tracer("promptetheus"); if no provider is
            configured this is OTel's no-op tracer, which is harmless.

    Raises:
        RuntimeError: if the optional otel extra is not installed.
    """

    def __init__(
        self,
        session: "Session | NoopSession | None" = None,
        tracer: "Tracer | None" = None,
    ) -> None:
        # Import lazily so importing this module never requires OpenTelemetry.
        otel_trace = _require_opentelemetry()

        if session is None:
            from ..session import current

            session = current()

        self.session = session
        self._tracer = (
            tracer if tracer is not None else otel_trace.get_tracer("promptetheus")
        )

    # -- core mirroring ----------------------------------------------------

    def mirror(self, event: Mapping[str, Any]) -> None:
        """Reflect an already-enveloped Promptetheus event onto an OTel span.

        Maps event["type"] to the span name, event["payload"] to
        promptetheus.<key> attributes, and attaches session_id, seq,
        and idempotency_key for correlation. Does not emit anything on the
        wrapped session — use this for events already in the Promptetheus stream
        (e.g. tapped from a transport). Best-effort: logs and swallows failures.
        """
        try:
            event_type = str(event.get("type", "event"))
            attributes: dict[str, Any] = {}

            session_id = event.get("session_id")
            if isinstance(session_id, str) and session_id:
                attributes["promptetheus.session_id"] = session_id
            seq = event.get("seq")
            if isinstance(seq, int) and not isinstance(seq, bool):
                attributes["promptetheus.seq"] = seq
            idempotency_key = event.get("idempotency_key")
            if isinstance(idempotency_key, str) and idempotency_key:
                attributes["promptetheus.idempotency_key"] = idempotency_key

            payload = event.get("payload")
            if isinstance(payload, Mapping):
                attributes.update(_flatten_attributes("promptetheus", payload))

            metadata = event.get("metadata")
            if isinstance(metadata, Mapping):
                attributes.update(
                    _flatten_attributes("promptetheus.metadata", metadata)
                )

            # A point-in-time span: the Promptetheus event already happened, so we
            # open and immediately close a span carrying its attributes. Using the
            # context-manager form ensures the span is always ended.
            with self._tracer.start_as_current_span(event_type) as span:
                _set_attributes(span, attributes)
        except Exception:  # pragma: no cover - never raise into the caller
            logger.exception("Promptetheus OTel bridge failed mirroring event")

    def _emit_and_mirror(self, emit: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Call a bound Session helper, then mirror the returned event.

        The session helpers build and return the full enveloped event; mirroring
        the returned envelope keeps the OTel span faithful to what was recorded.
        Never raises: wrapped sessions normally swallow redactor/schema/transport
        errors, but custom/noop sessions may not, and mirror swallows span errors.
        """
        try:
            event = emit(*args, **kwargs)
        except Exception:
            logger.exception("Promptetheus OTel bridge failed forwarding event")
            return {}
        if isinstance(event, Mapping):
            self.mirror(event)
        return event if isinstance(event, dict) else {}

    # -- thin Session-compatible helpers -----------------------------------
    #
    # Each forwards to the matching public Session helper and mirrors the
    # resulting envelope onto an OTel span. Signatures mirror Session's so the
    # bridge is a drop-in for this subset of the API.

    def event(
        self,
        type: str,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Forward a raw event to the session and mirror it onto an OTel span."""
        return self._emit_and_mirror(self.session.event, type, payload, metadata)

    def user_message(
        self, content: str, metadata: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._emit_and_mirror(self.session.user_message, content, metadata)

    def agent_message(
        self, content: str, metadata: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._emit_and_mirror(self.session.agent_message, content, metadata)

    def tool_call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        call_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._emit_and_mirror(
            self.session.tool_call, tool_name, arguments, call_id, metadata
        )

    def tool_result(
        self,
        call_id: str,
        result: Any = None,
        error: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._emit_and_mirror(
            self.session.tool_result, call_id, result, error, metadata
        )

    def retrieval(
        self,
        query: str,
        documents: list[Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._emit_and_mirror(self.session.retrieval, query, documents, metadata)

    def llm_call(
        self,
        model: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        messages_ref: str | None = None,
        prompt_ref: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._emit_and_mirror(
            self.session.llm_call,
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            messages_ref=messages_ref,
            prompt_ref=prompt_ref,
            metadata=metadata,
        )


def _set_attributes(span: Any, attributes: Mapping[str, Any]) -> None:
    """Set span attributes one at a time, skipping any that OTel rejects.

    Setting attributes individually means one bad value can't drop the rest; any
    rejection is logged at debug and skipped. Never raises.
    """
    for key, value in attributes.items():
        try:
            span.set_attribute(key, value)
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "Promptetheus OTel bridge skipped attribute %r", key, exc_info=True
            )


__all__ = ["OpenTelemetryBridge"]
