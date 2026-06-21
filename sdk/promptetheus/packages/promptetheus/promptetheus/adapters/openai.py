"""OpenAI adapter for Promptetheus.

A thin wrapper over a user-supplied OpenAI client (openai.OpenAI or
openai.AsyncOpenAI) and the public Promptetheus
Session API. The adapter performs the real chat
completion and emits the matching standard events through the existing
Session helpers (llm_call, tool_call, agent_message). It
introduces no adapter-only event types and no server-side behavior — anything it
does, a caller could do by hand with the public session.* helpers.

OpenAI is an optional dependency, and the adapter never constructs a client: the
user passes their own. The openai library is therefore never imported at
module load time (the adapter duck-types the client and response objects), so
importing this module without openai installed must not fail.

Telemetry is best-effort: the wrapped completion call runs and raises exactly as
it normally would; only the event emission around it is wrapped in a guard that
logs and swallows failures, preserving the SDK's never-crash guarantee.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from ._base import extract_token_usage

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import Session

logger = logging.getLogger("promptetheus")


class _WrappedCompletions:
    """Thin chat.completions proxy that instruments create.

    Wraps the real chat.completions object so create measures latency,
    calls through, and emits Promptetheus events from the response. Every other
    attribute is delegated to the underlying object unchanged.
    """

    def __init__(self, adapter: "OpenAIAdapter", completions: Any) -> None:
        self._adapter = adapter
        self._completions = completions

    def create(self, *args: Any, **kwargs: Any) -> Any:
        """Call the real chat.completions.create and emit telemetry.

        The real call (and any exception it raises) is never suppressed. If the
        provider returns an awaitable (async client), the awaitable is returned
        untouched and telemetry is skipped — async clients should use
        OpenAIAdapter.acreate.

        When stream=True the provider returns an iterable of chunks rather than a
        full response. We return a thin wrapper that yields those chunks
        unchanged and, once iteration completes, emits a single llm_call
        carrying total latency, time-to-first-token (ttft_ms), final token usage
        when present, and streamed=True metadata — plus the streamed text as an
        agent_message when available. The non-streaming path is unchanged.
        """
        start = time.monotonic()
        response = self._completions.create(*args, **kwargs)
        # An AsyncOpenAI client returns a coroutine here; do not block or inspect
        # it. Callers on async clients should use adapter.acreate(...).
        if _is_awaitable(response):
            return response
        if kwargs.get("stream"):
            return _StreamingResponse(self._adapter, response, start)
        latency_ms = int((time.monotonic() - start) * 1000)
        self._adapter._emit_from_response(response, latency_ms)
        return response

    async def acreate(self, *args: Any, **kwargs: Any) -> Any:
        """Async counterpart of create for AsyncOpenAI clients.

        With stream=True the awaited result is an async iterable of chunks; it is
        wrapped so iterating it yields chunks unchanged and emits one llm_call
        (latency, ttft_ms, usage, streamed=True) plus the streamed text after the
        stream completes.
        """
        start = time.monotonic()
        response = await self._completions.create(*args, **kwargs)
        if kwargs.get("stream"):
            return _AsyncStreamingResponse(self._adapter, response, start)
        latency_ms = int((time.monotonic() - start) * 1000)
        self._adapter._emit_from_response(response, latency_ms)
        return response

    def __getattr__(self, name: str) -> Any:
        # Delegate everything else (e.g. with_raw_response) to the real obj.
        return getattr(self._completions, name)


class _WrappedChat:
    """Thin chat proxy exposing an instrumented completions."""

    def __init__(self, adapter: "OpenAIAdapter", chat: Any) -> None:
        self._chat = chat
        self.completions = _WrappedCompletions(adapter, chat.completions)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


class OpenAIAdapter:
    """Instrument an OpenAI client against a Promptetheus Session.

    Usage mirrors the underlying client, so existing call sites change only at
    construction:

        client = openai.OpenAI()
        client = OpenAIAdapter(client)          # default session = current()
        resp = client.chat.completions.create(model="gpt-4o", messages=[...])

    On each completion the adapter emits, through the public Session helpers:

    - session.llm_call(model=..., input_tokens=..., output_tokens=...,
      latency_ms=...) — token counts are included only when the response
      carries a usage block (skipped for streaming responses).
    - session.tool_call(tool_name, arguments, call_id) for each tool call on
      the assistant message.
    - session.agent_message(content) for assistant text, when present and
      emit_agent_message is enabled (default).

    Raw prompts and messages are never placed in the event stream. Pass a
    messages_ref/prompt_ref (e.g. a hash or external id) at construction
    if you want the llm_call event to reference them.

    The adapter is duck-typed over the client: it never imports openai and
    never constructs a client, so it works with sync and async clients and does
    not require the library to import this module.
    """

    def __init__(
        self,
        client: Any,
        session: "Session | None" = None,
        *,
        emit_agent_message: bool = True,
        messages_ref: str | None = None,
        prompt_ref: str | None = None,
    ) -> None:
        if session is None:
            from ..session import current

            session = current()  # type: ignore[assignment]

        self._client = client
        self.session = session
        self._emit_agent_message = emit_agent_message
        self._messages_ref = messages_ref
        self._prompt_ref = prompt_ref

        # Expose an instrumented chat so adapter.chat.completions.create
        # works like the real client. Built defensively: a client without a
        # chat attribute (unusual) simply has no wrapped surface.
        chat = getattr(client, "chat", None)
        self.chat = _WrappedChat(self, chat) if chat is not None else None

    # -- convenience pass-throughs ----------------------------------------

    def create(self, *args: Any, **kwargs: Any) -> Any:
        """Shortcut for adapter.chat.completions.create (sync clients)."""
        return self.chat.completions.create(*args, **kwargs)

    async def acreate(self, *args: Any, **kwargs: Any) -> Any:
        """Shortcut for the async completion path (AsyncOpenAI clients)."""
        return await self.chat.completions.acreate(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # Anything not instrumented (embeddings, files, ...) passes through to
        # the wrapped client unchanged.
        return getattr(self._client, name)

    # -- emission ---------------------------------------------------------

    def _emit_from_response(self, response: Any, latency_ms: int) -> None:
        """Emit llm_call plus any tool/agent events from a response.

        Best-effort and fully guarded: a malformed or unexpected response shape
        never propagates an exception into the caller's code path.
        """
        try:
            model = _safe_str(_get(response, "model"))
            input_tokens, output_tokens = extract_token_usage(response)

            self.session.llm_call(
                model=model or "unknown",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                messages_ref=self._messages_ref,
                prompt_ref=self._prompt_ref,
            )

            message = _first_message(response)
            if message is None:
                return

            self._emit_tool_calls(message)

            if self._emit_agent_message:
                content = _safe_str(_get(message, "content"))
                if content:
                    self.session.agent_message(content)
        except Exception:  # pragma: no cover - defensive; never crash the caller
            logger.exception("Promptetheus OpenAI adapter failed emitting events")

    def _emit_tool_calls(self, message: Any) -> None:
        """Emit a tool_call for each tool call on the assistant message."""
        tool_calls = _get(message, "tool_calls") or []
        for tool_call in tool_calls:
            try:
                function = _get(tool_call, "function")
                name = _safe_str(_get(function, "name")) or "unknown"
                arguments = _coerce_arguments(_get(function, "arguments"))
                call_id = _safe_str(_get(tool_call, "id")) or None
                self.session.tool_call(name, arguments, call_id=call_id)
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "Promptetheus OpenAI adapter failed emitting tool_call"
                )

    def _emit_from_stream(
        self, accumulator: "_StreamAccumulator", latency_ms: int
    ) -> None:
        """Emit one llm_call (and any agent_message) from a finished stream.

        Called after the user has iterated a streaming response to completion.
        Mirrors _emit_from_response but reads the model / usage / text the
        accumulator gathered across chunks, and stamps streamed=True plus
        ttft_ms (time to first token) into the llm_call metadata. Fully guarded:
        a malformed chunk stream never propagates into the caller's loop.
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
                messages_ref=self._messages_ref,
                prompt_ref=self._prompt_ref,
                metadata=metadata,
            )

            if self._emit_agent_message and accumulator.text:
                self.session.agent_message(accumulator.text)
        except Exception:  # pragma: no cover - defensive; never crash the caller
            logger.exception(
                "Promptetheus OpenAI adapter failed emitting stream events"
            )


# -- streaming support (duck-typed, dependency-free) ----------------------


class _StreamAccumulator:
    """Gathers model, usage, ttft, and text across streamed chat chunks.

    Each OpenAI streaming chunk carries choices[0].delta.content (a text
    fragment) and a model; the final chunk (when the caller requested
    stream_options={"include_usage": True}) carries a usage block. We never
    require usage — it stays None when the provider does not send it.
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

    def observe(self, chunk: Any) -> None:
        """Fold one streamed chunk into the running totals. Never raises."""
        try:
            model = _safe_str(_get(chunk, "model"))
            if model:
                self.model = model

            # Usage typically arrives only on the final chunk; keep the last
            # non-empty reading.
            in_tokens, out_tokens = extract_token_usage(chunk)
            if in_tokens is not None:
                self.input_tokens = in_tokens
            if out_tokens is not None:
                self.output_tokens = out_tokens

            delta_text = _chunk_delta_text(chunk)
            if delta_text:
                if not self._text_parts and self.ttft_ms is None:
                    self.ttft_ms = int((time.monotonic() - self._start) * 1000)
                self._text_parts.append(delta_text)
        except Exception:  # pragma: no cover - defensive; never break iteration
            logger.exception("Promptetheus OpenAI adapter failed reading stream chunk")

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)


class _StreamingResponse:
    """Thin sync iterator wrapper over a streamed completion.

    Yields the provider's chunks unchanged so the caller's loop is unaffected,
    folds each chunk into a _StreamAccumulator, and on stream completion emits
    one llm_call plus the streamed text. Other attributes (e.g. a context
    manager's close) delegate to the wrapped stream.
    """

    def __init__(self, adapter: "OpenAIAdapter", stream: Any, start: float) -> None:
        self._adapter = adapter
        self._stream = stream
        self._accumulator = _StreamAccumulator(start)
        self._emitted = False

    def __iter__(self) -> "Any":
        return self

    def __next__(self) -> Any:
        try:
            chunk = next(self._stream)
        except StopIteration:
            self._finish()
            raise
        self._accumulator.observe(chunk)
        return chunk

    def _finish(self) -> None:
        if self._emitted:
            return
        self._emitted = True
        self._adapter._emit_from_stream(
            self._accumulator, self._accumulator.elapsed_ms()
        )

    def __enter__(self) -> "_StreamingResponse":
        # Support `with client.chat.completions.create(stream=True) as s:` shape.
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
    """Thin async iterator wrapper over a streamed completion (async clients)."""

    def __init__(self, adapter: "OpenAIAdapter", stream: Any, start: float) -> None:
        self._adapter = adapter
        self._stream = stream
        self._accumulator = _StreamAccumulator(start)
        self._emitted = False

    def __aiter__(self) -> "Any":
        return self

    async def __anext__(self) -> Any:
        try:
            chunk = await self._stream.__anext__()
        except StopAsyncIteration:
            self._finish()
            raise
        self._accumulator.observe(chunk)
        return chunk

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


def _chunk_delta_text(chunk: Any) -> str | None:
    """Return the text fragment carried by a streamed chunk's first choice.

    Reads choices[0].delta.content, the standard OpenAI streaming shape. Any
    other / malformed shape yields None so iteration is never disturbed.
    """
    choices = _get(chunk, "choices")
    if not choices:
        return None
    try:
        first = choices[0]
    except (IndexError, TypeError, KeyError):  # pragma: no cover - defensive
        return None
    delta = _get(first, "delta")
    if delta is None:
        return None
    return _safe_str(_get(delta, "content"))


# -- module-level helpers (duck-typed, dependency-free) -------------------


def _is_awaitable(obj: Any) -> bool:
    """True if obj looks like a coroutine/awaitable (async client return)."""
    import inspect

    return inspect.isawaitable(obj)


def _get(obj: Any, name: str) -> Any:
    """Read name from a pydantic-style object or a plain dict; never raise."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _safe_str(value: Any) -> str | None:
    """Coerce a value to str for event fields, or None when absent."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:  # pragma: no cover - defensive
        return None


def _first_message(response: Any) -> Any:
    """Return the first choice's assistant message, or None."""
    choices = _get(response, "choices")
    if not choices:
        return None
    try:
        first = choices[0]
    except (IndexError, TypeError, KeyError):  # pragma: no cover - defensive
        return None
    return _get(first, "message")


def _coerce_arguments(arguments: Any) -> dict[str, Any]:
    """Normalize tool-call arguments to a dict for the tool_call payload.

    OpenAI returns function arguments as a JSON string. Parse it when possible;
    otherwise wrap the raw value so the event still carries something useful and
    never crashes on malformed JSON.
    """
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return dict(arguments)
    if isinstance(arguments, str):
        import json

        try:
            parsed = json.loads(arguments)
        except (ValueError, TypeError):
            return {"raw": arguments}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": arguments}


__all__ = ["OpenAIAdapter"]
