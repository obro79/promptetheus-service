"""LangChain callback adapter for Promptetheus.

A thin LangChain BaseCallbackHandler that maps LangChain's callback events
onto the public Promptetheus Session helpers
(llm_call,
tool_call,
tool_result,
agent_message). It introduces no
adapter-only event types and no server-side behavior — everything it emits, a
caller could emit by hand with the public session.* helpers.

LangChain (langchain_core) is an optional dependency. A LangChain callback
handler must subclass langchain_core.callbacks.BaseCallbackHandler, but
importing this module must NOT require langchain_core to be installed. The
subclass is therefore defined *lazily*: the public symbol
PromptetheusCallbackHandler is a factory that — only when called — imports
langchain_core, dynamically defines the handler subclass, and returns a
ready-to-use instance:

    from promptetheus.adapters import PromptetheusCallbackHandler

    chain.invoke(inputs, config={"callbacks": [PromptetheusCallbackHandler()]})

If langchain_core is not installed, *calling* the factory raises a clear
RuntimeError pointing at the promptetheus[langchain] extra. Merely
importing this module never imports LangChain.

As with every Promptetheus adapter, instrumentation is best-effort: callback
methods log and swallow telemetry failures so the observed chain never crashes
because telemetry is unavailable.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ._base import BoundedRunState, require_extra, run_key

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")


def _extract_usage(response: Any) -> dict[str, int]:
    """Best-effort token usage extraction from a LangChain LLMResult.

    LangChain exposes token usage inconsistently across providers and versions:
    aggregate counts live in response.llm_output["token_usage"] (or
    ["usage"]) for many chat models, while newer message-based providers put
    per-message counts in generation.message.usage_metadata. We try both and
    return only the keys we could resolve. Never raises.
    """
    usage: dict[str, int] = {}

    def _coerce(target: dict[str, int], key: str, value: Any) -> None:
        if value is None:
            return
        try:
            target[key] = int(value)
        except (TypeError, ValueError):
            return

    try:
        llm_output = getattr(response, "llm_output", None)
        if isinstance(llm_output, dict):
            token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
            if isinstance(token_usage, dict):
                _coerce(
                    usage,
                    "input_tokens",
                    token_usage.get("prompt_tokens")
                    if token_usage.get("prompt_tokens") is not None
                    else token_usage.get("input_tokens"),
                )
                _coerce(
                    usage,
                    "output_tokens",
                    token_usage.get("completion_tokens")
                    if token_usage.get("completion_tokens") is not None
                    else token_usage.get("output_tokens"),
                )
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Promptetheus LangChain adapter failed reading llm_output usage",
            exc_info=True,
        )

    if "input_tokens" in usage and "output_tokens" in usage:
        return usage

    # Fall back to per-generation usage_metadata (e.g. AIMessage.usage_metadata).
    try:
        generations = getattr(response, "generations", None) or []
        for batch in generations:
            for generation in batch or []:
                message = getattr(generation, "message", None)
                usage_metadata = getattr(message, "usage_metadata", None)
                if isinstance(usage_metadata, dict):
                    _coerce(usage, "input_tokens", usage_metadata.get("input_tokens"))
                    _coerce(usage, "output_tokens", usage_metadata.get("output_tokens"))
                if "input_tokens" in usage and "output_tokens" in usage:
                    return usage
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Promptetheus LangChain adapter failed reading usage_metadata",
            exc_info=True,
        )

    return usage


def _extract_model(serialized: Any, kwargs: Any) -> str:
    """Best-effort model identifier from on_*_start arguments.

    LangChain passes the model in invocation_params (model /
    model_name) and sometimes in serialized. Falls back to
    "unknown" so llm_call always has the required model argument.
    """
    try:
        invocation_params = (
            kwargs.get("invocation_params") if isinstance(kwargs, dict) else None
        )
        if isinstance(invocation_params, dict):
            model = invocation_params.get("model") or invocation_params.get(
                "model_name"
            )
            if isinstance(model, str) and model:
                return model
        if isinstance(serialized, dict):
            kw = serialized.get("kwargs")
            if isinstance(kw, dict):
                model = kw.get("model") or kw.get("model_name")
                if isinstance(model, str) and model:
                    return model
            name = serialized.get("name")
            if isinstance(name, str) and name:
                return name
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Promptetheus LangChain adapter failed reading model name", exc_info=True
        )
    return "unknown"


def _tool_name(serialized: Any) -> str:
    """Best-effort tool name from the on_tool_start serialized mapping."""
    try:
        if isinstance(serialized, dict):
            name = serialized.get("name")
            if isinstance(name, str) and name:
                return name
    except Exception:  # pragma: no cover - defensive
        pass
    return "tool"


def PromptetheusCallbackHandler(session: "Session | NoopSession | None" = None) -> Any:
    """Build a LangChain callback handler that records to a Promptetheus session.

    Pass the result to LangChain's callbacks list:

        chain.invoke(inputs, config={"callbacks": [PromptetheusCallbackHandler()]})

    Args:
        session: The Promptetheus session to record into. Defaults to the
            currently-active session (promptetheus.current), captured at
            handler-creation time, which yields a no-op session when no session
            is active.

    Returns:
        An instance of a langchain_core.callbacks.BaseCallbackHandler
        subclass, ready to drop into LangChain's callbacks.

    Raises:
        RuntimeError: if the optional langchain extra is not installed.
    """
    callbacks_module = require_extra(
        "langchain_core.callbacks", "langchain", "PromptetheusCallbackHandler"
    )
    base_handler_cls = callbacks_module.BaseCallbackHandler

    if session is None:
        from ..session import current

        session = current()

    handler_session = session

    class _PromptetheusCallbackHandler(base_handler_cls):  # type: ignore[misc, valid-type]
        """LangChain callback handler that emits Promptetheus events.

        Thin by construction: every callback maps to a public Session
        helper, keyed by LangChain's run_id so starts and ends correlate.
        Telemetry failures are logged and swallowed, never raised into the
        observed chain.
        """

        def __init__(self) -> None:
            super().__init__()
            self.session = handler_session
            # run_id (str) -> {"start": monotonic seconds, "model": str}, capped
            # so a long-lived handler cannot accumulate orphaned pending runs.
            self._llm_runs = BoundedRunState()

        # -- LLM / chat model lifecycle -----------------------------------

        def on_llm_start(
            self,
            serialized: dict[str, Any],
            prompts: list[str],
            *,
            run_id: UUID,
            **kwargs: Any,
        ) -> None:
            """Stash the start time and resolved model for this LLM run."""
            self._start_llm_run(serialized, run_id, kwargs)

        def on_chat_model_start(
            self,
            serialized: dict[str, Any],
            messages: list[list[Any]],
            *,
            run_id: UUID,
            **kwargs: Any,
        ) -> None:
            """Stash the start time and resolved model for this chat run."""
            self._start_llm_run(serialized, run_id, kwargs)

        def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
            """Emit llm_call with model, token usage, and latency."""
            try:
                run = self._llm_runs.pop(run_key(run_id), None)
                model = (run or {}).get("model", "unknown")
                latency_ms: int | None = None
                started = (run or {}).get("start")
                if started is not None:
                    latency_ms = int((time.monotonic() - started) * 1000)

                usage = _extract_usage(response)
                self.session.llm_call(
                    model,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    latency_ms=latency_ms,
                    metadata={"run_id": run_key(run_id)},
                )
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangChain adapter failed emitting llm_call"
                )

        def on_llm_error(
            self, error: BaseException, *, run_id: UUID, **kwargs: Any
        ) -> None:
            """Drop stashed state for a failed LLM run (no event emitted)."""
            self._llm_runs.pop(run_key(run_id), None)

        # -- Tool lifecycle ------------------------------------------------

        def on_tool_start(
            self,
            serialized: dict[str, Any],
            input_str: str,
            *,
            run_id: UUID,
            **kwargs: Any,
        ) -> None:
            """Emit tool_call keyed by run_id."""
            try:
                self.session.tool_call(
                    tool_name=_tool_name(serialized),
                    arguments={"input": input_str},
                    call_id=run_key(run_id),
                )
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangChain adapter failed emitting tool_call"
                )

        def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
            """Emit tool_result correlated to the on_tool_start call."""
            try:
                self.session.tool_result(call_id=run_key(run_id), result=output)
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangChain adapter failed emitting tool_result"
                )

        def on_tool_error(
            self, error: BaseException, *, run_id: UUID, **kwargs: Any
        ) -> None:
            """Emit tool_result carrying the tool error string."""
            try:
                self.session.tool_result(call_id=run_key(run_id), error=str(error))
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangChain adapter failed emitting tool error"
                )

        # -- Text / agent actions (optional) ------------------------------

        def on_agent_action(self, action: Any, *, run_id: UUID, **kwargs: Any) -> None:
            """Emit an agent_message summarizing the agent's chosen action."""
            try:
                log = getattr(action, "log", None)
                tool = getattr(action, "tool", None)
                content = (
                    log if isinstance(log, str) and log else f"agent action: {tool}"
                )
                self.session.agent_message(content=str(content))
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangChain adapter failed emitting agent_message"
                )

        def on_text(self, text: str, *, run_id: UUID, **kwargs: Any) -> None:
            """Emit an agent_message for free-form intermediate text."""
            try:
                if text:
                    self.session.agent_message(content=str(text))
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangChain adapter failed emitting agent_message"
                )

        # -- internal ------------------------------------------------------

        def _start_llm_run(self, serialized: Any, run_id: UUID, kwargs: Any) -> None:
            try:
                # BoundedRunState evicts the oldest orphaned run so the map
                # stays bounded across a long-lived handler.
                self._llm_runs.set(
                    run_key(run_id),
                    {
                        "start": time.monotonic(),
                        "model": _extract_model(serialized, kwargs),
                    },
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "Promptetheus LangChain adapter failed recording llm start"
                )

    return _PromptetheusCallbackHandler()


__all__ = ["PromptetheusCallbackHandler"]
