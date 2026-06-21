"""CrewAI event-bus adapter for Promptetheus.

A thin bridge between CrewAI's event bus and the public Promptetheus
Session helpers. CrewAI emits framework events
(agent/task/tool/LLM lifecycle) through a process-wide event bus exposed under
crewai.utilities.events (older builds: crewai_events). This adapter
registers listeners on that bus and maps each event it understands onto a
standard Session helper:

- LLM-call *completed* events  -> llm_call
- tool-usage *started* events  -> tool_call
- tool-usage *finished/errored* events -> tool_result
- agent / task step events     -> agent_message

It introduces no adapter-only event types and no server-side behavior —
everything it emits, a caller could emit by hand with the public session.*
helpers.

crewai is an optional dependency. Importing this module must NOT require
crewai to be installed: the bus and its event classes are imported *lazily*,
only when CrewAIAdapter is constructed. Without the extra, constructing
the adapter raises a clear RuntimeError naming the crewai extra:

    from promptetheus.adapters import CrewAIAdapter

    handle = CrewAIAdapter()          # registers listeners on the CrewAI bus
    try:
        crew.kickoff(...)
    finally:
        handle.stop()                  # deregister (also: with CrewAIAdapter() as h)

CrewAI's event API varies considerably across versions: the module path, the
bus singleton name, and the concrete event class names have all changed. This
adapter therefore feature-detects everything (getattr / try/except),
wires the listeners it can confirm, and clearly TODO-comments anything that
could not be resolved rather than guessing. Listener callbacks log and swallow
all telemetry failures, so an instrumentation problem never raises into CrewAI's
own execution path.
"""

from __future__ import annotations

import itertools
import logging
from collections import defaultdict, deque
from types import TracebackType
from typing import TYPE_CHECKING, Any

from ._base import extract_token_usage

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")


# Candidate import paths for the CrewAI events package, newest first. CrewAI
# moved the events module from the top-level crewai_events package into
# crewai.utilities.events (and exposes it again as crewai.events on some
# builds). We try each in order and use the first that imports.
_EVENTS_MODULES = (
    "crewai.utilities.events",
    "crewai.events",
    "crewai_events",
)

# Candidate attribute names for the singleton event bus on the events module.
_BUS_ATTRS = ("crewai_event_bus", "event_bus", "crewai_events")

# CrewAI event class names, grouped by how we map them. The names and the field
# names referenced below are lib-verified against the CrewAI source
# (crewai.events.types.{llm_events,tool_usage_events,agent_events,task_events})
# but the package itself is NOT installed in this environment, so the live bus
# wiring is review-verified, not exercised here. We register every class that is
# actually present on the resolved events module and ignore the rest; each tuple
# lists known aliases.
#
# LLMCallCompletedEvent carries model (LLMEventBase.model) and a usage dict
# (prompt_tokens / completion_tokens) we forward to llm_call.
_LLM_COMPLETED_EVENTS = ("LLMCallCompletedEvent",)
# ToolUsageStartedEvent carries tool_name + tool_args -> tool_call.
_TOOL_STARTED_EVENTS = ("ToolUsageStartedEvent",)
# ToolUsageFinishedEvent carries output -> tool_result.
_TOOL_FINISHED_EVENTS = ("ToolUsageFinishedEvent",)
# ToolUsageErrorEvent carries error -> tool_result(error=...).
_TOOL_ERROR_EVENTS = ("ToolUsageErrorEvent",)
# Step completion -> a summarizing agent_message. AgentExecutionCompletedEvent
# exposes output: str; TaskCompletedEvent exposes output: TaskOutput (stringified
# when emitted). Both are read via the "output" attribute below.
_AGENT_STEP_EVENTS = (
    "AgentExecutionCompletedEvent",
    "TaskCompletedEvent",
)
# TODO(crewai-version): the following are observed on some CrewAI releases but
# their payload shape is unstable, so they are intentionally NOT wired yet to
# avoid emitting noise or guessing field names:
#   - LLMCallStartedEvent (no usage/model on start; we emit on completion).
#   - AgentExecutionStartedEvent / TaskStartedEvent (duplicate the
#     completion events without adding signal).
#   - CrewKickoffStartedEvent / CrewKickoffCompletedEvent (run-level;
#     the Promptetheus Session already brackets the run).
# Wire these once their payload contracts are confirmed for a target version.


def _require_crewai_bus() -> Any:
    """Import and return the CrewAI event bus, or raise a clear error.

    Tries each known events module path and bus attribute name. Raised only when
    CrewAIAdapter is actually constructed, so importing this module
    never requires the optional crewai extra.
    """
    events_module = None
    last_exc: BaseException | None = None
    for module_path in _EVENTS_MODULES:
        try:
            import importlib

            events_module = importlib.import_module(module_path)
            break
        except Exception as exc:  # pragma: no cover - exercised only without extra
            last_exc = exc

    if events_module is None:
        raise RuntimeError(
            "CrewAIAdapter requires the optional 'crewai' extra. "
            "Install it with: pip install 'promptetheus[crewai]'"
        ) from last_exc

    for attr in _BUS_ATTRS:
        bus = getattr(events_module, attr, None)
        if bus is not None:
            return events_module, bus

    # The events module imported but the bus singleton was not where we expect.
    raise RuntimeError(
        "CrewAIAdapter could not locate the CrewAI event bus on "
        f"{getattr(events_module, '__name__', '<crewai events>')!r}. "
        "This usually means an unsupported 'crewai' version; "
        "install a compatible one with: pip install 'promptetheus[crewai]'"
    )


def _resolve_event_classes(events_module: Any, names: tuple[str, ...]) -> list[Any]:
    """Return the event classes from names that exist on the events module."""
    resolved: list[Any] = []
    for name in names:
        cls = getattr(events_module, name, None)
        if cls is not None:
            resolved.append(cls)
    return resolved


def _coerce_int(value: Any) -> int | None:
    """Best-effort positive-or-zero int coercion (rejects bool); else None."""
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly
        return None
    if isinstance(value, int):
        return value
    return None


def _first_attr(obj: Any, *names: str) -> Any:
    """Return the first present, non-None attribute among names."""
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


class CrewAIAdapter:
    """Register Promptetheus listeners on the CrewAI event bus.

    Constructing the adapter resolves the CrewAI event bus and registers one
    handler per confirmed event family, each mapping to a public Session
    helper. The returned instance is a *handle*: call stop (alias
    detach) to deregister, or use it as a context manager:

        with CrewAIAdapter(session) as handle:
            crew.kickoff(...)

    session defaults to promptetheus.current (the active session, or
    a no-op session when none is active), so the adapter is safe to construct
    even outside an observed run.

    Raises:
        RuntimeError: if the optional crewai extra is not installed (or the
            installed version exposes no recognizable event bus).
    """

    def __init__(self, session: "Session | NoopSession | None" = None) -> None:
        if session is None:
            from ..session import current

            session = current()
        self.session = session

        events_module, bus = _require_crewai_bus()
        self._events_module = events_module
        self._bus = bus
        # (event_class, handler) pairs we registered, for best-effort teardown.
        self._registered: list[tuple[Any, Any]] = []
        self._call_counter = itertools.count(1)
        self._pending_tool_calls: defaultdict[tuple[str, str], deque[str]] = (
            defaultdict(deque)
        )
        self._stopped = False

        self._register_all()

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> "CrewAIAdapter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self.stop()
        return False

    # -- teardown ----------------------------------------------------------

    def stop(self) -> None:
        """Deregister every listener this adapter added. Idempotent, never raises.

        CrewAI's bus does not expose a stable public de-registration API across
        versions, so teardown is best-effort: we try common removal shapes and,
        failing those, neutralize our handlers so they emit nothing further.
        """
        if self._stopped:
            return
        self._stopped = True
        for event_cls, handler in self._registered:
            self._deregister(event_cls, handler)

    # Alias matching the task's ".stop()/detach" handle contract.
    def detach(self) -> None:
        """Alias for stop."""
        self.stop()

    # -- registration ------------------------------------------------------

    def _register_all(self) -> None:
        """Wire every confirmed event family to its Session mapping."""
        self._register(_LLM_COMPLETED_EVENTS, self._on_llm_completed)
        self._register(_TOOL_STARTED_EVENTS, self._on_tool_started)
        self._register(_TOOL_FINISHED_EVENTS, self._on_tool_finished)
        self._register(_TOOL_ERROR_EVENTS, self._on_tool_error)
        self._register(_AGENT_STEP_EVENTS, self._on_agent_step)

    def _register(self, names: tuple[str, ...], handler: Any) -> None:
        """Register handler for each resolvable event class in names."""
        for event_cls in _resolve_event_classes(self._events_module, names):
            try:
                self._bus_on(event_cls, handler)
                self._registered.append((event_cls, handler))
            except Exception:  # pragma: no cover - defensive across versions
                logger.debug(
                    "Promptetheus CrewAI adapter could not register handler for %r",
                    getattr(event_cls, "__name__", event_cls),
                    exc_info=True,
                )

    def _bus_on(self, event_cls: Any, handler: Any) -> None:
        """Subscribe handler to event_cls on the CrewAI bus.

        Both shapes are lib-verified against the CrewAI source: the bus exposes a
        public register_handler(EventType, handler) and a bus.on(EventType)
        decorator (which registers the wrapped callable and returns it
        unchanged). We prefer register_handler and fall back to the decorator.
        Handlers are invoked as handler(source, event) (CrewAI also allows a
        third runtime-state arg, which our *args signature tolerates).
        """
        register_handler = getattr(self._bus, "register_handler", None)
        if callable(register_handler):
            register_handler(event_cls, handler)
            return

        on = getattr(self._bus, "on", None)
        if callable(on):
            # bus.on(EventType) returns a decorator that registers the
            # wrapped callable; apply it directly to our bound handler.
            decorator = on(event_cls)
            if callable(decorator):
                decorator(handler)
                return

        raise RuntimeError("CrewAI event bus exposes no recognized registration API")

    def _deregister(self, event_cls: Any, handler: Any) -> None:
        """Best-effort removal of one registered handler; never raises."""
        try:
            # Preferred: the lib-verified public off(EventType, handler) removal
            # API. The aliases cover older/forked builds that named it
            # differently. off is the real method on current CrewAI.
            for method_name in ("off", "unregister_handler", "remove_handler"):
                method = getattr(self._bus, method_name, None)
                if callable(method):
                    method(event_cls, handler)
                    return

            # Fallback for builds without a public removal API: CrewAI keeps
            # handlers in internal per-event-type sets (_sync_handlers /
            # _async_handlers, frozensets) or, on older builds, a _handlers dict
            # of lists. Drop ours from whichever shape is present.
            for attr in ("_sync_handlers", "_async_handlers"):
                handlers = getattr(self._bus, attr, None)
                if isinstance(handlers, dict) and event_cls in handlers:
                    bucket = handlers[event_cls]
                    if handler in bucket:
                        # frozenset is immutable: rebuild without our handler.
                        handlers[event_cls] = type(bucket)(
                            h for h in bucket if h is not handler
                        )
                        return
            handlers = getattr(self._bus, "_handlers", None)
            if isinstance(handlers, dict):
                bucket = handlers.get(event_cls)
                if isinstance(bucket, list) and handler in bucket:
                    bucket.remove(handler)
                    return
        except Exception:  # pragma: no cover - defensive across versions
            logger.debug(
                "Promptetheus CrewAI adapter failed deregistering %r",
                getattr(event_cls, "__name__", event_cls),
                exc_info=True,
            )

    # -- event handlers (CrewAI bus -> Session helpers) --------------------
    #
    # CrewAI invokes handlers as handler(source, event). We accept a flexible
    # signature so version differences (extra/missing positional args) cannot
    # raise into the bus. Every handler is fully guarded.

    def _on_llm_completed(self, *args: Any, **kwargs: Any) -> None:
        """Map an LLM-call-completed event to session.llm_call."""
        if self._stopped:
            return
        try:
            event = self._event_arg(args, kwargs)
            model = (
                self._safe_str(_first_attr(event, "model", "model_name")) or "unknown"
            )
            input_tokens, output_tokens = self._read_usage(event)
            latency_ms = _coerce_int(
                _first_attr(event, "latency_ms", "duration_ms", "elapsed_ms")
            )
            self.session.llm_call(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
        except Exception:  # pragma: no cover - helpers already swallow
            logger.exception("Promptetheus CrewAI adapter failed emitting llm_call")

    def _on_tool_started(self, *args: Any, **kwargs: Any) -> None:
        """Map a tool-usage-started event to session.tool_call."""
        if self._stopped:
            return
        try:
            event = self._event_arg(args, kwargs)
            tool_name = (
                self._safe_str(_first_attr(event, "tool_name", "name")) or "tool"
            )
            arguments = _first_attr(event, "tool_args", "args", "arguments", "input")
            self.session.tool_call(
                tool_name=tool_name,
                arguments=arguments
                if isinstance(arguments, dict)
                else self._wrap_arg(arguments),
                call_id=self._start_call_id(event, tool_name),
            )
        except Exception:  # pragma: no cover - helpers already swallow
            logger.exception("Promptetheus CrewAI adapter failed emitting tool_call")

    def _on_tool_finished(self, *args: Any, **kwargs: Any) -> None:
        """Map a tool-usage-finished event to session.tool_result."""
        if self._stopped:
            return
        try:
            event = self._event_arg(args, kwargs)
            tool_name = (
                self._safe_str(_first_attr(event, "tool_name", "name")) or "tool"
            )
            output = _first_attr(event, "output", "result")
            self.session.tool_result(
                call_id=self._finish_call_id(event, tool_name),
                result=output,
            )
        except Exception:  # pragma: no cover - helpers already swallow
            logger.exception("Promptetheus CrewAI adapter failed emitting tool_result")

    def _on_tool_error(self, *args: Any, **kwargs: Any) -> None:
        """Map a tool-usage-error event to session.tool_result(error=...)."""
        if self._stopped:
            return
        try:
            event = self._event_arg(args, kwargs)
            tool_name = (
                self._safe_str(_first_attr(event, "tool_name", "name")) or "tool"
            )
            error = _first_attr(event, "error", "exception", "message")
            self.session.tool_result(
                call_id=self._finish_call_id(event, tool_name),
                error=str(error) if error is not None else "tool error",
            )
        except Exception:  # pragma: no cover - helpers already swallow
            logger.exception("Promptetheus CrewAI adapter failed emitting tool error")

    def _on_agent_step(self, *args: Any, **kwargs: Any) -> None:
        """Map an agent/task step-completed event to session.agent_message."""
        if self._stopped:
            return
        try:
            event = self._event_arg(args, kwargs)
            content = _first_attr(event, "output", "result", "answer", "text")
            if content is None:
                # Fall back to a terse description so the step is still observed.
                label = self._safe_str(_first_attr(event, "agent_role", "task", "role"))
                content = f"agent step: {label}" if label else "agent step"
            self.session.agent_message(content=str(content))
        except Exception:  # pragma: no cover - helpers already swallow
            logger.exception(
                "Promptetheus CrewAI adapter failed emitting agent_message"
            )

    # -- payload helpers ---------------------------------------------------

    @staticmethod
    def _event_arg(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        """Pick the event object out of CrewAI's handler(source, event) call.

        CrewAI calls handlers positionally as (source, event); some versions
        pass the event as the sole arg or as event=. We take the last
        positional (the event) or the event keyword, defaulting to an empty
        object so attribute reads degrade to None instead of raising.
        """
        if "event" in kwargs and kwargs["event"] is not None:
            return kwargs["event"]
        if args:
            return args[-1]
        return object()

    @staticmethod
    def _wrap_arg(value: Any) -> dict[str, Any]:
        """Normalize a non-dict tool-argument payload into a dict for the event."""
        if value is None:
            return {}
        return {"input": value}

    def _start_call_id(self, event: Any, tool_name: str) -> str | None:
        """Return a unique call id for a tool start and remember it for finish."""
        explicit = self._explicit_call_id(event)
        if explicit is not None:
            return explicit
        if not tool_name:
            return None
        key = self._tool_key(event, tool_name)
        call_id = self._new_call_id(key)
        self._pending_tool_calls[key].append(call_id)
        return call_id

    def _finish_call_id(self, event: Any, tool_name: str) -> str | None:
        """Return the pending call id for a finish/error event, or mint one."""
        explicit = self._explicit_call_id(event)
        if explicit is not None:
            return explicit
        if not tool_name:
            return None
        key = self._tool_key(event, tool_name)
        pending = self._pending_tool_calls.get(key)
        if pending:
            call_id = pending.popleft()
            if not pending:
                self._pending_tool_calls.pop(key, None)
            return call_id
        return self._new_call_id(key)

    @staticmethod
    def _explicit_call_id(event: Any) -> str | None:
        """Read an explicit CrewAI/future per-call id when available."""
        call_id = _first_attr(event, "call_id", "tool_call_id", "id")
        if isinstance(call_id, str) and call_id:
            return call_id
        if call_id is not None:
            return str(call_id)
        return None

    @staticmethod
    def _tool_key(event: Any, tool_name: str) -> tuple[str, str]:
        """Correlate starts/results by acting agent and tool name."""
        agent = _first_attr(event, "agent_id", "agent_key", "agent_role")
        agent_key = agent if isinstance(agent, str) and agent else "agent"
        return agent_key, tool_name

    def _new_call_id(self, key: tuple[str, str]) -> str:
        agent, tool_name = key
        return f"crewai:{agent}:{tool_name}:{next(self._call_counter)}"

    @staticmethod
    def _read_usage(event: Any) -> tuple[int | None, int | None]:
        """Pull input_tokens / output_tokens from a CrewAI LLM event.

        Token usage may sit directly on the event or under a usage /
        token_usage / usage_metadata object or dict, with provider-style key
        aliases. The shared extractor unwraps those holders, resolves the
        prompt/input and completion/output aliases, and falls back to reading
        the keys off the event itself when no dedicated container is present.
        Robust to absence and non-integer values; returns (None, None) when
        usage is unavailable.
        """
        return extract_token_usage(event)

    @staticmethod
    def _safe_str(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None


__all__ = ["CrewAIAdapter"]
