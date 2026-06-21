"""LiteLLM callback adapter for Promptetheus.

A thin bridge between LiteLLM's callback system and the public Promptetheus
Session helpers. LiteLLM lets you register loggers that fire after every
completion: it exposes a litellm.callbacks list (and the older
litellm.success_callback / litellm.failure_callback lists) and a CustomLogger
base class whose log_success_event(kwargs, response_obj, start_time, end_time)
method is invoked once per successful call. This adapter registers such a logger
and maps each success event onto a single standard Session helper, llm_call,
carrying the model, prompt/completion token usage, and measured latency.

It introduces no adapter-only event types and no server-side behavior --
everything it emits, a caller could emit by hand with the public session.*
helpers.

litellm is an optional dependency. Importing this module must NOT require
litellm to be installed: the library is imported lazily, only when
LiteLLMAdapter is constructed. Without the extra, constructing the adapter
raises a clear RuntimeError naming the litellm extra:

    from promptetheus.adapters import LiteLLMAdapter

    handle = LiteLLMAdapter()          # registers a logger on litellm.callbacks
    try:
        litellm.completion(model="gpt-4o-mini", messages=[...])
    finally:
        handle.detach()                # deregister (also: with LiteLLMAdapter() as h)

Logger callbacks log and swallow all telemetry failures, so an instrumentation
problem never raises into LiteLLM's own completion path.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import TYPE_CHECKING, Any

from ._base import extract_token_usage, require_extra, safe_str

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")


def _require_litellm() -> Any:
    """Import and return the litellm module, or raise a clear error.

    Raised only when LiteLLMAdapter is actually constructed, so importing this
    module never requires the optional litellm extra.
    """
    return require_extra("litellm", "litellm", "LiteLLMAdapter")


def _build_custom_logger_class(litellm: Any) -> Any:
    """Define a CustomLogger subclass over the installed litellm, lazily.

    LiteLLM's CustomLogger lives at litellm.integrations.custom_logger (and is
    re-exported as litellm.CustomLogger on current builds). We subclass it so the
    logger is a first-class LiteLLM callback. Defined here, after litellm is
    confirmed importable, so this module never imports litellm at load time.
    """
    base_cls = getattr(litellm, "CustomLogger", None)
    if base_cls is None:
        from litellm.integrations.custom_logger import CustomLogger as base_cls  # type: ignore[no-redef]

    class _PromptetheusLiteLLMLogger(base_cls):  # type: ignore[misc, valid-type]
        """LiteLLM CustomLogger that emits one llm_call per completion.

        Thin by construction: the only thing it does is read model, token
        usage, and latency off LiteLLM's success-event arguments and forward
        them to the public Session.llm_call helper. Telemetry failures are
        logged and swallowed, never raised into LiteLLM's run loop.
        """

        def __init__(self, adapter: "LiteLLMAdapter") -> None:
            super().__init__()
            self._adapter = adapter

        def log_success_event(
            self,
            kwargs: Any,
            response_obj: Any,
            start_time: Any,
            end_time: Any,
        ) -> None:
            """Emit llm_call for one successful completion (sync path)."""
            self._adapter._emit_success(kwargs, response_obj, start_time, end_time)

        async def async_log_success_event(
            self,
            kwargs: Any,
            response_obj: Any,
            start_time: Any,
            end_time: Any,
        ) -> None:
            """Emit llm_call for one successful completion (async path)."""
            self._adapter._emit_success(kwargs, response_obj, start_time, end_time)

    return _PromptetheusLiteLLMLogger


class LiteLLMAdapter:
    """Register a Promptetheus logger on LiteLLM's callback list.

    Constructing the adapter lazily imports litellm, builds a CustomLogger
    subclass bound to this adapter, and appends it to litellm.callbacks so every
    successful completion emits one llm_call. The returned instance is a
    handle: call detach (alias stop) to deregister, or use it as a context
    manager:

        with LiteLLMAdapter(session) as handle:
            litellm.completion(model="gpt-4o-mini", messages=[...])

    session defaults to promptetheus.current (the active session, or a no-op
    session when none is active), so the adapter is safe to construct even
    outside an observed run.

    Raises:
        RuntimeError: if the optional litellm extra is not installed.
    """

    def __init__(self, session: "Session | NoopSession | None" = None) -> None:
        if session is None:
            from ..session import current

            session = current()
        self.session = session

        litellm = _require_litellm()
        self._litellm = litellm

        logger_cls = _build_custom_logger_class(litellm)
        self._logger = logger_cls(self)
        self._registered = False
        self._stopped = False

        self._register()

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> "LiteLLMAdapter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self.detach()
        return False

    # -- registration / teardown ------------------------------------------

    def _register(self) -> None:
        """Append our logger to litellm.callbacks (best-effort, never raises).

        LiteLLM's primary registration surface is the litellm.callbacks list;
        appending a CustomLogger instance there enables both the sync and async
        success hooks. We append only to callbacks to avoid double-firing.
        """
        try:
            callbacks = getattr(self._litellm, "callbacks", None)
            if isinstance(callbacks, list):
                callbacks.append(self._logger)
                self._registered = True
            else:  # pragma: no cover - defensive across litellm versions
                logger.debug(
                    "Promptetheus LiteLLM adapter found no litellm.callbacks list to register on"
                )
        except Exception:  # pragma: no cover - defensive across versions
            logger.exception(
                "Promptetheus LiteLLM adapter failed registering its logger"
            )

    def detach(self) -> None:
        """Remove our logger from litellm.callbacks. Idempotent, never raises."""
        if self._stopped:
            return
        self._stopped = True
        try:
            callbacks = getattr(self._litellm, "callbacks", None)
            if isinstance(callbacks, list):
                # Remove every reference to our logger (it was appended once, but
                # be defensive against accidental duplicate registration).
                callbacks[:] = [cb for cb in callbacks if cb is not self._logger]
        except Exception:  # pragma: no cover - defensive across versions
            logger.exception(
                "Promptetheus LiteLLM adapter failed deregistering its logger"
            )

    # Alias matching the documented ".stop()/detach" handle contract.
    def stop(self) -> None:
        """Alias for detach."""
        self.detach()

    # -- emission ----------------------------------------------------------

    def _emit_success(
        self,
        kwargs: Any,
        response_obj: Any,
        start_time: Any,
        end_time: Any,
    ) -> None:
        """Emit one llm_call from a LiteLLM success event. Fully guarded.

        Reads the model off kwargs (LiteLLM's standard logging payload), token
        usage off response_obj.usage (prompt_tokens / completion_tokens), and
        latency from end_time - start_time (LiteLLM passes datetimes; we also
        tolerate float seconds). A malformed or unexpected shape never raises
        into LiteLLM's run loop.
        """
        if self._stopped:
            return
        try:
            model = _read_model(kwargs, response_obj)
            input_tokens, output_tokens = _read_usage(response_obj)
            latency_ms = _latency_ms(start_time, end_time)
            self.session.llm_call(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
        except Exception:  # pragma: no cover - helpers already swallow
            logger.exception("Promptetheus LiteLLM adapter failed emitting llm_call")


# -- module-level helpers (duck-typed, dependency-free) -------------------


def _get(obj: Any, name: str) -> Any:
    """Read name from a pydantic-style object or a plain dict; never raise."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _read_model(kwargs: Any, response_obj: Any) -> str:
    """Best-effort model identifier from the success-event arguments.

    LiteLLM places the requested model in kwargs["model"]; the response object
    echoes the resolved model as response_obj.model. Falls back to "unknown" so
    llm_call always has its required model argument.
    """
    model = safe_str(_get(kwargs, "model"))
    if model:
        return model
    model = safe_str(_get(response_obj, "model"))
    if model:
        return model
    return "unknown"


def _read_usage(response_obj: Any) -> tuple[int | None, int | None]:
    """Extract (prompt_tokens, completion_tokens) from a LiteLLM response.

    LiteLLM returns OpenAI-shaped responses, so usage sits on
    response_obj.usage as prompt_tokens / completion_tokens, with the
    input_tokens / output_tokens aliases tolerated. Delegates to the shared
    extractor and returns (None, None) when usage is absent.
    """
    return extract_token_usage(response_obj)


def _latency_ms(start_time: Any, end_time: Any) -> int | None:
    """Compute call latency in milliseconds from LiteLLM's start/end markers.

    LiteLLM passes datetime objects (their difference is a timedelta); some
    paths pass float epoch seconds. Both yield milliseconds; anything else
    yields None so the event simply omits latency.
    """
    if start_time is None or end_time is None:
        return None
    try:
        delta = end_time - start_time
    except TypeError:  # pragma: no cover - defensive across marker types
        return None
    seconds = getattr(delta, "total_seconds", None)
    if callable(seconds):
        return int(seconds() * 1000)
    try:
        return int(float(delta) * 1000)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


__all__ = ["LiteLLMAdapter"]
