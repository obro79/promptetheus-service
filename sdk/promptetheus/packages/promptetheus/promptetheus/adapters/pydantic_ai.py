"""Pydantic-AI adapter for Promptetheus.

A thin wrapper over a Pydantic-AI Agent and the public Promptetheus Session
helpers. The adapter runs the agent and walks the resulting message history,
mapping each model request/response and tool call onto a standard Session
helper:

- a ModelResponse  -> llm_call (model + token usage) plus, for each part:
    - a TextPart            -> agent_message
    - a ToolCallPart        -> tool_call (tool name + args, keyed by tool_call_id)
- a ToolReturnPart (on the following ModelRequest) -> tool_result
- a RetryPromptPart that carries a tool_name        -> tool_result(error=...)

It introduces no adapter-only event types and no server-side behavior —
everything it emits, a caller could emit by hand with the public session.*
helpers. Tool calls and their returns correlate by Pydantic-AI's
tool_call_id, so a tool_call and its tool_result share a call_id.

pydantic_ai is an optional dependency. Importing this module must NOT require
it: the library is imported lazily, only when the adapter is constructed.
Without the extra, constructing the adapter raises a clear RuntimeError naming
the pydantic-ai extra:

    from promptetheus.adapters import PydanticAIAdapter

    adapter = PydanticAIAdapter(agent)             # default session = current()
    result = adapter.run_sync("Book a room")       # mirrors agent.run_sync

Pydantic-AI is NOT installed in this environment, so this adapter is
REVIEW-VERIFIED, not lib-verified: the Agent.run/run_sync surface, the
message-history shape (ModelRequest/ModelResponse and their parts:
TextPart, ToolCallPart, ToolReturnPart, RetryPromptPart), and the
ModelResponse.usage / model_name fields were checked against the Pydantic-AI
docs and source (pydantic_ai.messages and pydantic_ai.agent), and the fakes in
the tests mirror those shapes. The adapter reads every field defensively
(getattr / duck typing) so version drift degrades to a thinner event rather
than an exception.

Telemetry is best-effort: the wrapped agent run executes and raises exactly as
it normally would; only the event emission around it is guarded so a malformed
or unexpected message shape never propagates into the caller's code path.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from ._base import require_extra, safe_str

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")


def _require_pydantic_ai() -> Any:
    """Import and return the pydantic_ai module, or raise a clear error.

    Raised only when the adapter is actually constructed, so importing this
    module never requires the optional pydantic-ai extra.
    """
    return require_extra("pydantic_ai", "pydantic-ai", "PydanticAIAdapter")


class PydanticAIAdapter:
    """Instrument a Pydantic-AI Agent against a Promptetheus Session.

    Wrap an agent at construction and call run / run_sync / run_stream on the
    adapter exactly as you would on the agent. Each call runs the real agent and
    then emits, through the public Session helpers:

    - session.llm_call(model, input_tokens, output_tokens) for each model
      response in the run's message history.
    - session.agent_message(content) for assistant text parts.
    - session.tool_call(tool_name, arguments, call_id) for each tool call the
      model requested, and session.tool_result(call_id, result/error) for the
      matching tool return (correlated by Pydantic-AI's tool_call_id).

    session defaults to promptetheus.current (the active session, or a no-op
    session when none is active), so the adapter is safe to construct even
    outside an observed run. Raw prompts and tool payloads are summarized as
    strings; nothing the adapter emits leaves the public event contract.

    Raises:
        RuntimeError: if the optional pydantic-ai extra is not installed.
    """

    def __init__(
        self, agent: Any, session: "Session | NoopSession | None" = None
    ) -> None:
        # Fail fast and clearly when the extra is missing — even though the
        # adapter never touches pydantic_ai symbols directly (it duck-types the
        # agent and messages), constructing it without the lib installed is a
        # configuration error worth surfacing immediately.
        _require_pydantic_ai()

        if session is None:
            from ..session import current

            session = current()

        self._agent = agent
        self.session = session

    # -- run surfaces (mirror Agent.run / run_sync) -----------------------

    def run_sync(self, *args: Any, **kwargs: Any) -> Any:
        """Run the agent synchronously, then emit events from its messages.

        Mirrors Agent.run_sync: the real call (and any exception it raises) is
        never suppressed. On success the run's message history is walked and the
        matching Session events are emitted before the result is returned.
        """
        start = time.monotonic()
        result = self._agent.run_sync(*args, **kwargs)
        self._emit_from_result(result, start)
        return result

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        """Async counterpart of run_sync (mirrors Agent.run)."""
        start = time.monotonic()
        result = await self._agent.run(*args, **kwargs)
        self._emit_from_result(result, start)
        return result

    def __getattr__(self, name: str) -> Any:
        # Anything not instrumented (e.g. run_stream, tool registration, model
        # settings) passes through to the wrapped agent unchanged.
        return getattr(self._agent, name)

    # -- emission ---------------------------------------------------------

    def _emit_from_result(self, result: Any, start: float) -> None:
        """Walk a run result's message history and emit Session events.

        Fully guarded: a malformed or unexpected message shape never propagates
        an exception into the caller's code path. Latency is split evenly across
        the model responses in the run as a best-effort per-call figure when no
        per-response timing is available.
        """
        try:
            messages = _all_messages(result)
            responses = [m for m in messages if _is_model_response(m)]
            total_ms = int((time.monotonic() - start) * 1000)
            per_call_ms = total_ms // len(responses) if responses else None

            for message in messages:
                if _is_model_response(message):
                    self._emit_response(message, per_call_ms)
                elif _is_model_request(message):
                    self._emit_request_returns(message)
        except Exception:  # pragma: no cover - defensive; never crash the caller
            logger.exception("Promptetheus Pydantic-AI adapter failed emitting events")

    def _emit_response(self, response: Any, latency_ms: int | None) -> None:
        """Emit one llm_call plus agent_message/tool_call parts for a response."""
        try:
            model = safe_str(_first_attr(response, "model_name", "model")) or "unknown"
            input_tokens, output_tokens = _read_usage(response)
            self.session.llm_call(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
        except Exception:  # pragma: no cover - helpers already swallow
            logger.exception(
                "Promptetheus Pydantic-AI adapter failed emitting llm_call"
            )

        for part in _parts(response):
            kind = _part_kind(part)
            try:
                if kind == "text":
                    content = safe_str(getattr(part, "content", None))
                    if content:
                        self.session.agent_message(content)
                elif kind == "tool-call":
                    self.session.tool_call(
                        tool_name=safe_str(getattr(part, "tool_name", None)) or "tool",
                        arguments=_coerce_arguments(getattr(part, "args", None)),
                        call_id=_call_id(part),
                    )
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus Pydantic-AI adapter failed emitting response part"
                )

    def _emit_request_returns(self, request: Any) -> None:
        """Emit a tool_result for each tool-return part on a model request.

        Pydantic-AI feeds tool outputs back to the model as parts of the next
        ModelRequest: a ToolReturnPart carries a successful result, while a
        RetryPromptPart that names a tool carries a tool error.
        """
        for part in _parts(request):
            kind = _part_kind(part)
            try:
                if kind == "tool-return":
                    self.session.tool_result(
                        call_id=_call_id(part),
                        result=_coerce_result(getattr(part, "content", None)),
                    )
                elif kind == "retry-prompt" and getattr(part, "tool_name", None):
                    self.session.tool_result(
                        call_id=_call_id(part),
                        error=_retry_error(part),
                    )
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus Pydantic-AI adapter failed emitting tool_result"
                )


# -- message-history helpers (duck-typed, dependency-free) ----------------


def _all_messages(result: Any) -> list[Any]:
    """Return the run's full message history as a list.

    Pydantic-AI exposes the history as result.all_messages() (a method). We
    fall back to a messages attribute / new_messages() so version or shape
    differences degrade to an empty list rather than raising.
    """
    for name in ("all_messages", "new_messages"):
        method = getattr(result, name, None)
        if callable(method):
            try:
                messages = method()
            except Exception:  # pragma: no cover - defensive
                continue
            if messages:
                return list(messages)
    messages = getattr(result, "messages", None)
    if messages:
        try:
            return list(messages)
        except TypeError:  # pragma: no cover - defensive
            return []
    return []


def _is_model_response(message: Any) -> bool:
    """True when message is a ModelResponse (assistant turn).

    Identified by class name so the check needs no import; ModelResponse
    carries response parts (text + tool calls) and a usage block.
    """
    return type(message).__name__ == "ModelResponse"


def _is_model_request(message: Any) -> bool:
    """True when message is a ModelRequest (carries tool returns / prompts)."""
    return type(message).__name__ == "ModelRequest"


def _parts(message: Any) -> list[Any]:
    """Return a message's parts list, or empty when absent/malformed."""
    parts = getattr(message, "parts", None)
    if not parts:
        return []
    try:
        return list(parts)
    except TypeError:  # pragma: no cover - defensive
        return []


def _part_kind(part: Any) -> str:
    """Classify a message part across Pydantic-AI versions.

    Prefers the part_kind discriminator each part carries
    ("text", "tool-call", "tool-return", "retry-prompt"); falls back to the
    class name so a part without the discriminator is still classified.
    """
    kind = getattr(part, "part_kind", None)
    if isinstance(kind, str) and kind:
        return kind
    name = type(part).__name__
    mapping = {
        "TextPart": "text",
        "ToolCallPart": "tool-call",
        "ToolReturnPart": "tool-return",
        "RetryPromptPart": "retry-prompt",
    }
    return mapping.get(name, name)


def _call_id(part: Any) -> str | None:
    """Correlation id shared between a tool_call and its tool_result.

    Pydantic-AI tags tool calls and their returns with a tool_call_id; both
    sides carry the same id, so a tool_call and its tool_result correlate.
    Returns None (so the Session mints its own id) only when the id is absent.
    """
    call_id = _first_attr(part, "tool_call_id", "call_id", "id")
    if call_id is None:
        return None
    return safe_str(call_id)


def _read_usage(response: Any) -> tuple[int | None, int | None]:
    """Extract (input_tokens, output_tokens) from a ModelResponse.

    Token counts live on response.usage (a Usage object or dict) under
    request_tokens / response_tokens, with input_tokens / output_tokens
    and provider-style prompt_tokens / completion_tokens accepted as aliases.
    Returns (None, None) when usage is unavailable.
    """
    usage = getattr(response, "usage", None)
    if callable(usage):  # some versions expose usage() as a method
        try:
            usage = usage()
        except Exception:  # pragma: no cover - defensive
            usage = None
    if usage is None:
        return None, None

    input_tokens = _as_int(
        _read(usage, "request_tokens", "input_tokens", "prompt_tokens")
    )
    output_tokens = _as_int(
        _read(usage, "response_tokens", "output_tokens", "completion_tokens")
    )
    return input_tokens, output_tokens


def _read(container: Any, *keys: str) -> Any:
    """Return the first present, non-None key from a dict or object."""
    for key in keys:
        if isinstance(container, dict):
            value = container.get(key)
        else:
            value = getattr(container, key, None)
        if value is not None:
            return value
    return None


def _first_attr(obj: Any, *names: str) -> Any:
    """Return the first present, non-None attribute among names."""
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _as_int(value: Any) -> int | None:
    """Coerce to int for token fields (rejects bool); None on failure."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _coerce_arguments(arguments: Any) -> dict[str, Any]:
    """Normalize a ToolCallPart's args to a dict for the tool_call payload.

    Pydantic-AI surfaces tool-call arguments as either a dict or a JSON string.
    Parse a string when possible; otherwise wrap the raw value so the event
    still carries something useful and never crashes on malformed JSON.
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


def _coerce_result(content: Any) -> Any:
    """Normalize a ToolReturnPart's content for the tool_result payload.

    Dicts and lists pass through; everything else is stringified so the event
    carries a stable, JSON-friendly value.
    """
    if content is None or isinstance(content, (dict, list, str, int, float, bool)):
        return content
    return safe_str(content)


def _retry_error(part: Any) -> str:
    """Build a tool-error string from a RetryPromptPart.

    The retry content is either a plain message or a list of validation-error
    dicts; we stringify whichever is present so tool_result carries the reason.
    """
    content = getattr(part, "content", None)
    text = safe_str(content)
    return text if text else "tool retry requested"


__all__ = ["PydanticAIAdapter"]
