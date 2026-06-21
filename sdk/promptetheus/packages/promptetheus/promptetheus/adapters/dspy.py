"""DSPy callback adapter for Promptetheus.

A thin bridge between DSPy's callback system and the public Promptetheus
Session helpers. DSPy 2.x exposes a callback protocol: a subclass of
dspy.utils.callback.BaseCallback registered on dspy.settings.callbacks (via
dspy.settings.configure(callbacks=[...])). DSPy invokes the callback's
on_lm_start/on_lm_end, on_module_start/on_module_end, and
on_tool_start/on_tool_end hooks as it runs language models, modules, and tools.

This adapter maps each hook it understands onto a standard Session helper:

- LM calls          -> llm_call (model, token usage, latency)
- module execution  -> a run-tree span plus an agent_message summarizing output
- tool execution    -> tool_call on start, tool_result on end

It introduces no adapter-only event types and no server-side behavior --
everything it emits, a caller could emit by hand with the public session.*
helpers.

dspy is an optional dependency. Importing this module must NOT require dspy to
be installed: the BaseCallback base class is imported lazily, only when
DSPyAdapter is constructed. Without the extra, constructing the adapter raises a
clear RuntimeError naming the dspy extra:

    import dspy
    from promptetheus.adapters import DSPyAdapter

    dspy.settings.configure(callbacks=[DSPyAdapter()])
    program(question="...")

DSPy is NOT installed in this environment, so the live callback wiring here is
REVIEW-VERIFIED against the documented dspy.utils.callback.BaseCallback API
(call_id / instance / inputs on start; call_id / outputs / exception on end),
not exercised against the real library. The handlers feature-detect everything
they read and are fully guarded: a telemetry failure logs and swallows rather
than raising into DSPy's own execution path.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from ._base import BoundedRunState, extract_token_usage, run_key, safe_str

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")

# Cap on pending module spans (started-but-not-ended). Unlike the LM-call map
# (a BoundedRunState), evicting a pending span must also close it, so this map
# stays a plain dict with explicit eviction. Oldest pending span evicts first.
_MAX_PENDING_SPANS = 1024


def _require_dspy_base_callback() -> Any:
    """Import and return dspy.utils.callback.BaseCallback, or raise a clear error.

    DSPy moved the callback base class across versions; we try the documented
    locations newest-first. Raised only when DSPyAdapter is actually
    constructed, so importing this module never requires the optional dspy extra.
    """
    last_exc: BaseException | None = None
    for module_path, attr in (
        ("dspy.utils.callback", "BaseCallback"),
        ("dspy.utils", "BaseCallback"),
        ("dspy", "BaseCallback"),
    ):
        try:
            import importlib

            module = importlib.import_module(module_path)
            base = getattr(module, attr, None)
            if base is not None:
                return base
        except Exception as exc:  # pragma: no cover - exercised only without extra
            last_exc = exc

    raise RuntimeError(
        "DSPyAdapter requires the optional 'dspy' extra. "
        "Install it with: pip install 'promptetheus[dspy]'"
    ) from last_exc


def _get(obj: Any, name: str) -> Any:
    """Read name from a pydantic-style object or a plain dict; never raise."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _lm_model(instance: Any, inputs: Any) -> str:
    """Best-effort model identifier for an LM call.

    DSPy LMs (dspy.LM / dspy.clients.lm.LM) expose the model as instance.model;
    some inputs dicts also carry a model key. Falls back to "unknown" so
    llm_call always has its required model argument.
    """
    model = _first_present(
        _get(instance, "model"),
        _get(instance, "model_name"),
        _get(inputs, "model") if isinstance(inputs, dict) else None,
    )
    return safe_str(model) or "unknown"


def _tool_name(instance: Any, inputs: Any) -> str:
    """Best-effort tool name for a tool call.

    DSPy wraps callables as dspy.Tool, which exposes name; some builds expose
    func_name or __name__. Falls back to "tool".
    """
    name = _first_present(
        _get(instance, "name"),
        _get(instance, "func_name"),
        _get(instance, "__name__"),
    )
    return safe_str(name) or "tool"


def _module_name(instance: Any) -> str:
    """Best-effort name for a DSPy module (used as the span name)."""
    name = _first_present(
        _get(instance, "name"),
        _get(type(instance), "__name__") if instance is not None else None,
    )
    return safe_str(name) or "module"


def _first_present(*values: Any) -> Any:
    """Return the first non-None value, or None."""
    for value in values:
        if value is not None:
            return value
    return None


def _read_usage(outputs: Any) -> tuple[int | None, int | None]:
    """Pull (input_tokens, output_tokens) from an LM call's outputs.

    DSPy LM outputs carry usage inconsistently across versions: a usage dict
    with prompt_tokens / completion_tokens (OpenAI-style), or input_tokens /
    output_tokens directly. Delegates to the shared extractor, which unwraps a
    usage / token_usage / usage_metadata holder and tolerates both alias sets,
    returning (None, None) when usage is unavailable.
    """
    return extract_token_usage(outputs)


def _output_text(outputs: Any) -> str | None:
    """Best-effort human-readable summary of a module's outputs.

    DSPy modules return a dspy.Prediction (a dict-like of named fields). We
    prefer a common answer/response/output/completion field, then fall back to
    the stringified prediction. Returns None when there is nothing useful.
    """
    for field in ("answer", "response", "output", "completion", "text"):
        value = _get(outputs, field)
        text = safe_str(value)
        if text:
            return text
    text = safe_str(outputs)
    if text and text not in ("None", "{}"):
        return text
    return None


class DSPyAdapter:
    """A DSPy callback that records to a Promptetheus session.

    Register the instance on DSPy's settings so DSPy drives its callback hooks
    during a run:

        dspy.settings.configure(callbacks=[DSPyAdapter()])

    On each hook the adapter emits, through the public Session helpers:

    - session.llm_call(model, input_tokens, output_tokens, latency_ms) on
      on_lm_end, keyed by DSPy's call_id (token counts only when the LM output
      carries usage).
    - a session.span wrapping each module execution (opened on on_module_start,
      closed on on_module_end) plus a session.agent_message summarizing the
      module's output, so the run tree nests by module.
    - session.tool_call on on_tool_start and session.tool_result on
      on_tool_end, correlated by call_id.

    session defaults to promptetheus.current (the active session, or a no-op
    session when none is active), so the adapter is safe to construct even
    outside an observed run.

    The adapter subclasses dspy.utils.callback.BaseCallback, imported lazily at
    construction. Importing this module never requires dspy; only constructing
    DSPyAdapter does.

    Raises:
        RuntimeError: if the optional dspy extra is not installed.
    """

    # DSPyAdapter is a factory: it returns an instance of a BaseCallback
    # subclass defined lazily at call time (so the base class is imported only
    # when the adapter is constructed, never at module import).
    def __new__(cls, session: "Session | NoopSession | None" = None) -> Any:
        base_callback_cls = _require_dspy_base_callback()

        if session is None:
            from ..session import current

            session = current()

        handler_session = session

        class _DSPyCallback(base_callback_cls):  # type: ignore[misc, valid-type]
            """DSPy callback that emits Promptetheus events.

            Thin by construction: every hook maps to a public Session helper,
            keyed by DSPy's call_id so starts and ends correlate. Telemetry
            failures are logged and swallowed, never raised into DSPy.
            """

            def __init__(self) -> None:
                super().__init__()
                self.session = handler_session
                # call_id (str) -> {"start": monotonic seconds, "model": str}.
                # Bounded so a start with no matching end cannot accumulate
                # orphaned entries; the oldest pending entry evicts first.
                self._lm_calls = BoundedRunState()
                # call_id (str) -> span context manager, for module nesting.
                # Kept as a plain dict because evicting a pending span must also
                # close it (a side effect BoundedRunState does not perform).
                self._module_spans: dict[str, Any] = {}

            # -- LM lifecycle --------------------------------------------------

            def on_lm_start(
                self,
                call_id: str,
                instance: Any,
                inputs: dict[str, Any],
            ) -> None:
                """Stash the start time and resolved model for this LM call."""
                try:
                    self._lm_calls.set(
                        run_key(call_id),
                        {
                            "start": time.monotonic(),
                            "model": _lm_model(instance, inputs),
                        },
                    )
                except Exception:  # pragma: no cover - defensive
                    logger.exception(
                        "Promptetheus DSPy adapter failed recording lm start"
                    )

            def on_lm_end(
                self,
                call_id: str,
                outputs: Any,
                exception: BaseException | None = None,
            ) -> None:
                """Emit llm_call with model, token usage, and latency.

                A failed LM call (exception set) drops the stashed state without
                emitting an llm_call, matching the other adapters.
                """
                try:
                    run = self._lm_calls.pop(run_key(call_id), None)
                    if exception is not None:
                        return
                    model = (run or {}).get("model", "unknown")
                    latency_ms: int | None = None
                    started = (run or {}).get("start")
                    if started is not None:
                        latency_ms = int((time.monotonic() - started) * 1000)

                    input_tokens, output_tokens = _read_usage(outputs)
                    self.session.llm_call(
                        model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        latency_ms=latency_ms,
                        metadata={"call_id": run_key(call_id)},
                    )
                except Exception:  # pragma: no cover - helpers already swallow
                    logger.exception(
                        "Promptetheus DSPy adapter failed emitting llm_call"
                    )

            # -- module lifecycle ----------------------------------------------

            def on_module_start(
                self,
                call_id: str,
                instance: Any,
                inputs: dict[str, Any],
            ) -> None:
                """Open a run-tree span around the module's execution."""
                try:
                    spans = self._module_spans
                    while len(spans) >= _MAX_PENDING_SPANS:
                        old_key, old_span = next(iter(spans.items()))
                        spans.pop(old_key, None)
                        self._close_span(old_span)
                    span = self.session.span(_module_name(instance))
                    span.__enter__()
                    spans[run_key(call_id)] = span
                except Exception:  # pragma: no cover - defensive
                    logger.exception(
                        "Promptetheus DSPy adapter failed opening module span"
                    )

            def on_module_end(
                self,
                call_id: str,
                outputs: Any,
                exception: BaseException | None = None,
            ) -> None:
                """Emit an agent_message for the module output and close its span."""
                try:
                    if exception is None:
                        text = _output_text(outputs)
                        if text:
                            self.session.agent_message(content=text)
                except Exception:  # pragma: no cover - helpers already swallow
                    logger.exception(
                        "Promptetheus DSPy adapter failed emitting agent_message"
                    )
                finally:
                    span = self._module_spans.pop(run_key(call_id), None)
                    self._close_span(span)

            # -- tool lifecycle ------------------------------------------------

            def on_tool_start(
                self,
                call_id: str,
                instance: Any,
                inputs: dict[str, Any],
            ) -> None:
                """Emit tool_call keyed by call_id."""
                try:
                    arguments = (
                        inputs if isinstance(inputs, dict) else {"input": inputs}
                    )
                    self.session.tool_call(
                        tool_name=_tool_name(instance, inputs),
                        arguments=arguments,
                        call_id=run_key(call_id),
                    )
                except Exception:  # pragma: no cover - helpers already swallow
                    logger.exception(
                        "Promptetheus DSPy adapter failed emitting tool_call"
                    )

            def on_tool_end(
                self,
                call_id: str,
                outputs: Any,
                exception: BaseException | None = None,
            ) -> None:
                """Emit tool_result correlated to the on_tool_start call."""
                try:
                    if exception is not None:
                        self.session.tool_result(
                            call_id=run_key(call_id),
                            error=str(exception),
                        )
                    else:
                        self.session.tool_result(
                            call_id=run_key(call_id),
                            result=outputs,
                        )
                except Exception:  # pragma: no cover - helpers already swallow
                    logger.exception(
                        "Promptetheus DSPy adapter failed emitting tool_result"
                    )

            # -- internal ------------------------------------------------------

            @staticmethod
            def _close_span(span: Any) -> None:
                """Exit a span context manager, swallowing any failure."""
                if span is None:
                    return
                try:
                    span.__exit__(None, None, None)
                except Exception:  # pragma: no cover - defensive
                    logger.exception(
                        "Promptetheus DSPy adapter failed closing module span"
                    )

        return _DSPyCallback()


__all__ = ["DSPyAdapter"]
