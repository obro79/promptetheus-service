"""Anthropic adapter for Promptetheus.

A thin wrapper over a user-supplied Anthropic client (anthropic.Anthropic or
anthropic.AsyncAnthropic) and the public Promptetheus
Session API. The adapter performs the real
messages.create call and emits the matching standard events through the
existing Session helpers:

- one llm_call carrying model and (when the provider returns usage)
  input_tokens / output_tokens / latency_ms;
- one agent_message per text content block;
- one tool_call per tool_use content block.

It introduces no adapter-only event types and no server-side behavior — anything
it does, a caller could do by hand with the public session.* helpers.

The anthropic library is an optional dependency. This module **must import
without it installed**: the adapter instruments a *passed-in* client object
(duck-typed), so it never imports anthropic to function. anthropic is
imported lazily, and only for type/validation conveniences, never at module
import time.

Telemetry is best-effort: the wrapped call runs (and raises) exactly as the
underlying client would; only the event emission around it is guarded, so an
instrumentation failure never crashes or alters the caller's code path. Raw
prompts and messages are deliberately kept out of the event stream — the adapter
records token usage and model identity, not message content.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")


class AnthropicAdapter:
    """Instrument an Anthropic client against a Promptetheus Session.

    The adapter wraps a live Anthropic client (sync or async) and a Session.
    Its single surface is create, a faithful pass-through to the client's
    messages.create that performs the call, measures latency, and emits the
    standard llm_call / agent_message / tool_call events — it is not
    a new API surface.

    Usage:

        import anthropic
        from promptetheus.adapters import AnthropicAdapter

        client = AnthropicAdapter(anthropic.Anthropic())
        resp = client.create(model="claude-...", max_tokens=1024, messages=[...])

    session defaults to promptetheus.current (the active session, or a
    no-op session when none is active), so the adapter is safe to construct even
    outside an observed run.
    """

    def __init__(
        self,
        client: Any,
        session: "Session | NoopSession | None" = None,
    ) -> None:
        if session is None:
            from ..session import current

            session = current()

        self.client = client
        self.session = session

    # -- public surface ----------------------------------------------------

    def create(self, **kwargs: Any) -> Any:
        """Call the wrapped client's messages.create and emit events.

        The underlying call runs and raises normally; if it raises, the exception
        propagates to the caller untouched and no events are emitted (there is no
        response to instrument). On success the response is returned unchanged
        after best-effort telemetry.

        With stream=True the provider returns an iterable of stream events rather
        than a full Message. We return a thin wrapper that yields those events
        unchanged and, once iteration completes, emits a single llm_call carrying
        latency, time-to-first-token (ttft_ms), final token usage when present,
        and streamed=True metadata — plus the streamed text as an agent_message
        when available. The non-streaming path is unchanged.

        For AsyncAnthropic clients messages.create returns a coroutine;
        use acreate instead so latency is measured and events are emitted
        around the awaited result.
        """
        start = time.monotonic()
        response = self.client.messages.create(**kwargs)
        if kwargs.get("stream"):
            return _StreamingResponse(self, response, start)
        latency_ms = self._elapsed_ms(start)
        self._emit(response, latency_ms)
        return response

    async def acreate(self, **kwargs: Any) -> Any:
        """Async counterpart to create for AsyncAnthropic clients.

        Awaits the wrapped messages.create coroutine, measures latency around
        the await, and emits the same standard events. Telemetry is best-effort
        and never alters the awaited result or its exceptions.

        With stream=True the awaited result is an async iterable of stream
        events; it is wrapped so iterating yields events unchanged and emits one
        llm_call (latency, ttft_ms, usage, streamed=True) plus the streamed text
        after the stream completes.
        """
        start = time.monotonic()
        response = await self.client.messages.create(**kwargs)
        if kwargs.get("stream"):
            return _AsyncStreamingResponse(self, response, start)
        latency_ms = self._elapsed_ms(start)
        self._emit(response, latency_ms)
        return response

    # -- internal helpers --------------------------------------------------

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    def _emit(self, response: Any, latency_ms: int) -> None:
        """Translate an Anthropic Message response into standard events.

        Never raises into the caller: every step is guarded, and the underlying
        session.* helpers already swallow transport errors. A malformed or
        streamed response simply yields fewer (or no) events.
        """
        try:
            model = self._safe_str(getattr(response, "model", None))
            input_tokens, output_tokens = self._read_usage(response)
            # model is the one required field for an llm_call; emit even if a
            # streamed/partial response lacks usage so the call is still observed.
            self.session.llm_call(
                model=model or "unknown",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
        except Exception:  # pragma: no cover - defensive; helpers already swallow
            logger.exception("Promptetheus Anthropic adapter failed emitting llm_call")

        try:
            self._emit_content_blocks(response)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Promptetheus Anthropic adapter failed emitting content blocks"
            )

    def _emit_content_blocks(self, response: Any) -> None:
        """Emit an agent_message / tool_call per response content block."""
        content = getattr(response, "content", None)
        if not isinstance(content, (list, tuple)):
            return

        for block in content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text = getattr(block, "text", None)
                if isinstance(text, str) and text:
                    self.session.agent_message(text)
            elif block_type == "tool_use":
                name = self._safe_str(getattr(block, "name", None)) or "tool"
                arguments = getattr(block, "input", None)
                call_id = self._safe_str(getattr(block, "id", None))
                self.session.tool_call(
                    tool_name=name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    call_id=call_id or None,
                )

    def _emit_from_stream(
        self, accumulator: "_StreamAccumulator", latency_ms: int
    ) -> None:
        """Emit one llm_call (and any agent_message) from a finished stream.

        Called after the caller iterates a streaming response to completion.
        Mirrors _emit but reads the model / usage / text the accumulator
        gathered across stream events, and stamps streamed=True plus ttft_ms
        (time to first token) into the llm_call metadata. Fully guarded: a
        malformed event stream never propagates into the caller's loop.
        """
        try:
            metadata: dict[str, Any] = {"streamed": True}
            if accumulator.ttft_ms is not None:
                metadata["ttft_ms"] = accumulator.ttft_ms

            self.session.llm_call(
                model=accumulator.model or "unknown",
                input_tokens=accumulator.input_tokens,
                output_tokens=accumulator.output_tokens,
                latency_ms=latency_ms,
                metadata=metadata,
            )
        except Exception:  # pragma: no cover - defensive; helpers already swallow
            logger.exception(
                "Promptetheus Anthropic adapter failed emitting stream llm_call"
            )

        try:
            if accumulator.text:
                self.session.agent_message(accumulator.text)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Promptetheus Anthropic adapter failed emitting stream agent_message"
            )

    @staticmethod
    def _read_usage(response: Any) -> tuple[int | None, int | None]:
        """Pull input_tokens / output_tokens from response.usage.

        Robust to a missing usage object (e.g. streamed responses) and to
        non-integer values; returns (None, None) when usage is unavailable.
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return None, None
        return (
            AnthropicAdapter._coerce_int(getattr(usage, "input_tokens", None)),
            AnthropicAdapter._coerce_int(getattr(usage, "output_tokens", None)),
        )

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
            return None
        if isinstance(value, int):
            return value
        return None

    @staticmethod
    def _safe_str(value: Any) -> str | None:
        return value if isinstance(value, str) else None


# -- streaming support (duck-typed, dependency-free) ----------------------


def _stream_event_type(event: Any) -> str | None:
    """Return the .type of an Anthropic stream event (or None)."""
    value = getattr(event, "type", None)
    if value is None and isinstance(event, dict):
        value = event.get("type")
    return value if isinstance(value, str) else None


def _stream_get(obj: Any, name: str) -> Any:
    """Read name from an object or dict; never raise."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


class _StreamAccumulator:
    """Gathers model, usage, ttft, and text across Anthropic stream events.

    Anthropic streams a sequence of typed events. The ones we read:

    - message_start: carries message.model and message.usage.input_tokens.
    - content_block_delta: carries delta.text fragments (the streamed answer).
    - message_delta: carries usage.output_tokens for the completed message.

    Anything else is ignored. Usage is never required; counts stay None when the
    provider omits them.
    """

    def __init__(self, start: float) -> None:
        self._start = start
        self.model: str | None = None
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.ttft_ms: int | None = None
        self._text_parts: list[str] = []

    @property
    def text(self) -> str:
        return "".join(self._text_parts)

    def observe(self, event: Any) -> None:
        """Fold one stream event into the running totals. Never raises."""
        try:
            event_type = _stream_event_type(event)

            if event_type == "message_start":
                message = _stream_get(event, "message")
                model = _stream_get(message, "model")
                if isinstance(model, str) and model:
                    self.model = model
                usage = _stream_get(message, "usage")
                in_tokens = AnthropicAdapter._coerce_int(
                    _stream_get(usage, "input_tokens")
                )
                if in_tokens is not None:
                    self.input_tokens = in_tokens
                out_tokens = AnthropicAdapter._coerce_int(
                    _stream_get(usage, "output_tokens")
                )
                if out_tokens is not None:
                    self.output_tokens = out_tokens

            elif event_type == "content_block_delta":
                delta = _stream_get(event, "delta")
                text = _stream_get(delta, "text")
                if isinstance(text, str) and text:
                    if not self._text_parts and self.ttft_ms is None:
                        self.ttft_ms = int((time.monotonic() - self._start) * 1000)
                    self._text_parts.append(text)

            elif event_type == "message_delta":
                usage = _stream_get(event, "usage")
                out_tokens = AnthropicAdapter._coerce_int(
                    _stream_get(usage, "output_tokens")
                )
                if out_tokens is not None:
                    self.output_tokens = out_tokens
        except Exception:  # pragma: no cover - defensive; never break iteration
            logger.exception(
                "Promptetheus Anthropic adapter failed reading stream event"
            )

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)


class _StreamingResponse:
    """Thin sync iterator wrapper over a streamed Anthropic response.

    Yields the provider's stream events unchanged, folds each into a
    _StreamAccumulator, and on completion emits one llm_call plus the streamed
    text. Other attributes delegate to the wrapped stream.
    """

    def __init__(self, adapter: "AnthropicAdapter", stream: Any, start: float) -> None:
        self._adapter = adapter
        self._stream = stream
        self._accumulator = _StreamAccumulator(start)
        self._emitted = False

    def __iter__(self) -> Any:
        return self

    def __next__(self) -> Any:
        try:
            event = next(self._stream)
        except StopIteration:
            self._finish()
            raise
        self._accumulator.observe(event)
        return event

    def _finish(self) -> None:
        if self._emitted:
            return
        self._emitted = True
        self._adapter._emit_from_stream(
            self._accumulator, self._accumulator.elapsed_ms()
        )

    def __enter__(self) -> "_StreamingResponse":
        enter = getattr(self._stream, "__enter__", None)
        if callable(enter):
            enter()
        return self

    def __exit__(self, *exc: Any) -> Any:
        exit_ = getattr(self._stream, "__exit__", None)
        result = exit_(*exc) if callable(exit_) else None
        self._finish()
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _AsyncStreamingResponse:
    """Thin async iterator wrapper over a streamed Anthropic response."""

    def __init__(self, adapter: "AnthropicAdapter", stream: Any, start: float) -> None:
        self._adapter = adapter
        self._stream = stream
        self._accumulator = _StreamAccumulator(start)
        self._emitted = False

    def __aiter__(self) -> Any:
        return self

    async def __anext__(self) -> Any:
        try:
            event = await self._stream.__anext__()
        except StopAsyncIteration:
            self._finish()
            raise
        self._accumulator.observe(event)
        return event

    def _finish(self) -> None:
        if self._emitted:
            return
        self._emitted = True
        self._adapter._emit_from_stream(
            self._accumulator, self._accumulator.elapsed_ms()
        )

    async def __aenter__(self) -> "_AsyncStreamingResponse":
        enter = getattr(self._stream, "__aenter__", None)
        if callable(enter):
            await enter()
        return self

    async def __aexit__(self, *exc: Any) -> Any:
        exit_ = getattr(self._stream, "__aexit__", None)
        result = await exit_(*exc) if callable(exit_) else None
        self._finish()
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


__all__ = ["AnthropicAdapter"]
