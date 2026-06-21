"""LangGraph callback adapter for Promptetheus.

LangGraph runs on LangChain's callback system, so instrumenting a graph means
supplying a LangChain BaseCallbackHandler in the run config. This adapter builds
such a handler and maps the LangGraph/LangChain run events it sees onto the
public Promptetheus Session helpers:

- on_llm_end / on_chat_model output -> session.llm_call (model, token usage,
  latency)
- on_tool_start / on_tool_end -> session.tool_call / session.tool_result
- on_chain_start / on_chain_end -> a Session.span per graph node, so each node's
  work nests under its own run-tree node

It introduces no adapter-only event types and no server-side behavior —
everything it emits, a caller could emit by hand with the public session.*
helpers. That keeps the adapter thin by construction.

LangChain (langchain_core) is an optional dependency. A LangChain callback
handler must subclass langchain_core.callbacks.BaseCallbackHandler, but importing
this module must NOT require langchain_core to be installed. The subclass is
therefore defined lazily: the public symbol LangGraphAdapter is a factory that —
only when called — imports langchain_core, dynamically defines the handler
subclass, and returns a ready-to-use instance:

    from promptetheus.adapters import LangGraphAdapter

    graph.invoke(inputs, config={"callbacks": [LangGraphAdapter()]})

If langchain_core is not installed, calling the factory raises a clear
RuntimeError pointing at the promptetheus[langgraph] extra. Merely importing
this module never imports LangChain.

As with every Promptetheus adapter, instrumentation is best-effort: callback
methods log and swallow telemetry failures so the observed graph never crashes
because telemetry is unavailable.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ._base import BoundedRunState, require_extra, run_key as _run_key

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")

# Cap on pending (started-but-not-ended) runs of each kind. A long-lived handler
# reused across many graph invocations must not accumulate orphaned entries when
# a start fires with no matching end (e.g. cancellation). Insertion order is
# preserved by dict, so the oldest pending run is evicted first.
_MAX_PENDING_RUNS = 1024


def _require_langchain() -> Any:
    """Import and return langchain_core.callbacks or raise a clear error.

    Raised only when the factory is actually invoked, so importing this module
    never requires the optional langgraph extra. Delegates to the shared
    require_extra helper, which raises the same clear missing-extra error naming
    the langgraph extra.
    """
    return require_extra("langchain_core.callbacks", "langgraph", "LangGraphAdapter")


def _extract_usage(response: Any) -> dict[str, int]:
    """Best-effort token usage extraction from a LangChain LLMResult.

    LangChain exposes token usage inconsistently across providers and versions:
    aggregate counts live in response.llm_output["token_usage"] (or ["usage"])
    for many chat models, while newer message-based providers put per-message
    counts in generation.message.usage_metadata. We try both and return only the
    keys we could resolve. Never raises.
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
            "Promptetheus LangGraph adapter failed reading llm_output usage",
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
            "Promptetheus LangGraph adapter failed reading usage_metadata",
            exc_info=True,
        )

    return usage


def _extract_model(serialized: Any, kwargs: Any) -> str:
    """Best-effort model identifier from on_*_start arguments.

    LangChain passes the model in invocation_params (model / model_name) and
    sometimes in serialized. Falls back to "unknown" so llm_call always has the
    required model argument.
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
            "Promptetheus LangGraph adapter failed reading model name", exc_info=True
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


def _node_name(serialized: Any, kwargs: Any) -> str:
    """Best-effort graph-node name for an on_chain_start span.

    LangGraph tags each node run; the human-readable node name usually appears in
    the run name (serialized["name"]) and is also reflected in the run's tags
    (kwargs["name"]). Falls back to "node" so a span always has a name.
    """
    try:
        if isinstance(kwargs, dict):
            name = kwargs.get("name")
            if isinstance(name, str) and name:
                return name
        if isinstance(serialized, dict):
            name = serialized.get("name")
            if isinstance(name, str) and name:
                return name
            graph_id = serialized.get("id")
            if isinstance(graph_id, list) and graph_id:
                last = graph_id[-1]
                if isinstance(last, str) and last:
                    return last
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Promptetheus LangGraph adapter failed reading node name", exc_info=True
        )
    return "node"


# LangChain fires on_chain_start for every Runnable in a graph (sequences,
# lambdas, channel writers, the Pregel loop, ...), not just user-visible graph
# nodes. Opening a span for each produces a deep, noisy run tree, so spans are
# skipped for these framework-plumbing names; real named nodes still get a span.
def _is_noise_node(name: str) -> bool:
    if name in ("node", "Pregel", "PregelLoop", "LangGraph", "RunnableSeq"):
        return True
    return (
        name.startswith("Runnable")
        or name.startswith("Channel")
        or name.startswith("_")
    )


def LangGraphAdapter(session: "Session | NoopSession | None" = None) -> Any:
    """Build a LangChain callback handler that records a LangGraph run.

    Pass the result to LangGraph's callbacks list:

        graph.invoke(inputs, config={"callbacks": [LangGraphAdapter()]})

    Args:
        session: The Promptetheus session to record into. Defaults to the
            currently-active session (promptetheus.current), captured at
            handler-creation time, which yields a no-op session when no session
            is active.

    Returns:
        An instance of a langchain_core.callbacks.BaseCallbackHandler subclass,
        ready to drop into LangGraph's callbacks.

    Raises:
        RuntimeError: if the optional langgraph extra is not installed.
    """
    callbacks_module = _require_langchain()
    base_handler_cls = callbacks_module.BaseCallbackHandler

    if session is None:
        from ..session import current

        session = current()

    handler_session = session

    class _LangGraphCallbackHandler(base_handler_cls):  # type: ignore[misc, valid-type]
        """LangChain/LangGraph callback handler that emits Promptetheus events.

        Thin by construction: every callback maps to a public Session helper,
        keyed by LangChain's run_id so starts and ends correlate. Graph nodes
        (chains) open a Session.span so node work nests in the run tree.
        Telemetry failures are logged and swallowed, never raised into the
        observed graph.
        """

        def __init__(self) -> None:
            super().__init__()
            self.session = handler_session
            # run_id (str) -> {"start": monotonic seconds, "model": str}.
            # Bounded so orphaned LLM starts (a start with no matching end) cannot
            # accumulate without limit over a long-lived handler.
            self._llm_runs: BoundedRunState = BoundedRunState(
                max_size=_MAX_PENDING_RUNS
            )
            # run_id (str) -> active span context manager for a graph node.
            # Kept a plain dict because eviction must also close the evicted span
            # (BoundedRunState would drop it without calling __exit__).
            self._chain_spans: dict[str, Any] = {}

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
                run = self._llm_runs.pop(_run_key(run_id), None)
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
                    metadata={"run_id": _run_key(run_id)},
                )
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangGraph adapter failed emitting llm_call"
                )

        def on_llm_error(
            self, error: BaseException, *, run_id: UUID, **kwargs: Any
        ) -> None:
            """Drop stashed state for a failed LLM run (no event emitted)."""
            self._llm_runs.pop(_run_key(run_id), None)

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
                    call_id=_run_key(run_id),
                )
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangGraph adapter failed emitting tool_call"
                )

        def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
            """Emit tool_result correlated to the on_tool_start call."""
            try:
                self.session.tool_result(call_id=_run_key(run_id), result=output)
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangGraph adapter failed emitting tool_result"
                )

        def on_tool_error(
            self, error: BaseException, *, run_id: UUID, **kwargs: Any
        ) -> None:
            """Emit tool_result carrying the tool error string."""
            try:
                self.session.tool_result(call_id=_run_key(run_id), error=str(error))
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangGraph adapter failed emitting tool error"
                )

        # -- Chain / graph-node lifecycle ----------------------------------

        def on_chain_start(
            self,
            serialized: dict[str, Any],
            inputs: dict[str, Any],
            *,
            run_id: UUID,
            **kwargs: Any,
        ) -> None:
            """Open a Session.span for this graph node (chain) run.

            Entering the span emits a span_start state_change and stamps every
            event the node produces with the span id, giving each LangGraph node
            its own run-tree node. The span is closed on on_chain_end /
            on_chain_error.
            """
            try:
                node_name = _node_name(serialized, kwargs)
                if _is_noise_node(node_name):
                    # Framework plumbing, not a graph node: skip the span so the
                    # run tree only reflects real nodes. Its inner events nest
                    # under the enclosing real node instead.
                    return
                runs = self._chain_spans
                # Evict oldest orphaned spans so the map stays bounded.
                while len(runs) >= _MAX_PENDING_RUNS:
                    key, cm = next(iter(runs.items()))
                    runs.pop(key, None)
                    try:
                        cm.__exit__(None, None, None)
                    except Exception:  # pragma: no cover - defensive
                        pass
                cm = self.session.span(node_name)
                cm.__enter__()
                runs[_run_key(run_id)] = cm
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangGraph adapter failed opening node span"
                )

        def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
            """Close the graph-node span opened in on_chain_start."""
            self._close_chain_span(run_id)

        def on_chain_error(
            self, error: BaseException, *, run_id: UUID, **kwargs: Any
        ) -> None:
            """Close the graph-node span for a failed node run."""
            self._close_chain_span(run_id)

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
                    "Promptetheus LangGraph adapter failed emitting agent_message"
                )

        def on_text(self, text: str, *, run_id: UUID, **kwargs: Any) -> None:
            """Emit an agent_message for free-form intermediate text."""
            try:
                if text:
                    self.session.agent_message(content=str(text))
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangGraph adapter failed emitting agent_message"
                )

        # -- internal ------------------------------------------------------

        def _start_llm_run(self, serialized: Any, run_id: UUID, kwargs: Any) -> None:
            try:
                # BoundedRunState.set evicts the oldest entry when the cap is hit,
                # so orphaned starts cannot accumulate without bound.
                self._llm_runs.set(
                    _run_key(run_id),
                    {
                        "start": time.monotonic(),
                        "model": _extract_model(serialized, kwargs),
                    },
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "Promptetheus LangGraph adapter failed recording llm start"
                )

        def _close_chain_span(self, run_id: UUID) -> None:
            try:
                cm = self._chain_spans.pop(_run_key(run_id), None)
                if cm is not None:
                    cm.__exit__(None, None, None)
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LangGraph adapter failed closing node span"
                )

    return _LangGraphCallbackHandler()


__all__ = ["LangGraphAdapter"]
