"""LlamaIndex callback adapter for Promptetheus.

A thin LlamaIndex callback handler that maps LlamaIndex's CBEventType events
onto the public Promptetheus Session helpers
(llm_call,
tool_call,
tool_result,
retrieval). It introduces no adapter-only
event types and no server-side behavior — everything it emits, a caller could
emit by hand with the public session.* helpers.

LlamaIndex (llama_index) is an optional dependency. A LlamaIndex callback
handler must subclass
llama_index.core.callbacks.base_handler.BaseCallbackHandler, but importing
this module must NOT require llama_index to be installed. The subclass is
therefore defined *lazily*: the public symbol LlamaIndexAdapter is a
factory that — only when called — imports llama_index, dynamically defines
the handler subclass, and returns a ready-to-use instance:

    from promptetheus.adapters import LlamaIndexAdapter
    from llama_index.core.callbacks import CallbackManager

    handler = LlamaIndexAdapter()
    callback_manager = CallbackManager([handler])

If llama_index is not installed, *calling* the factory raises a clear
RuntimeError pointing at the promptetheus[llamaindex] extra. Merely
importing this module never imports LlamaIndex.

As with every Promptetheus adapter, instrumentation is best-effort: callback
methods log and swallow telemetry failures so the observed pipeline never
crashes because telemetry is unavailable.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from ._base import BoundedRunState

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from ..session import NoopSession, Session

logger = logging.getLogger("promptetheus")


def _require_llamaindex() -> Any:
    """Import and return the LlamaIndex callback API or raise a clear error.

    Returns a small namespace object exposing BaseCallbackHandler,
    CBEventType, and EventPayload. Raised only when the factory is
    actually invoked, so importing this module never requires the optional
    llamaindex extra.
    """
    try:
        from llama_index.core.callbacks.base_handler import (  # noqa: F401
            BaseCallbackHandler,
        )
        from llama_index.core.callbacks.schema import CBEventType, EventPayload

        return BaseCallbackHandler, CBEventType, EventPayload
    except Exception as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(
            "LlamaIndexAdapter requires the optional 'llamaindex' extra. "
            "Install it with: pip install 'promptetheus[llamaindex]'"
        ) from exc


def _event_key(event_id: Any) -> str:
    """Stable string key for a LlamaIndex event_id."""
    return str(event_id) if event_id else "unknown"


def _as_dict(payload: Any) -> dict[Any, Any]:
    """Return payload as a dict, or an empty dict if it is not mapping-like."""
    return payload if isinstance(payload, dict) else {}


def LlamaIndexAdapter(session: "Session | NoopSession | None" = None) -> Any:
    """Build a LlamaIndex callback handler that records to a Promptetheus session.

    Pass the result to LlamaIndex's CallbackManager:

        from llama_index.core.callbacks import CallbackManager

        callback_manager = CallbackManager([LlamaIndexAdapter()])

    Args:
        session: The Promptetheus session to record into. Defaults to the
            currently-active session (promptetheus.current), captured at
            handler-creation time, which yields a no-op session when no session
            is active.

    Returns:
        An instance of a
        llama_index.core.callbacks.base_handler.BaseCallbackHandler
        subclass, ready to drop into a LlamaIndex CallbackManager.

    Raises:
        RuntimeError: if the optional llamaindex extra is not installed.
    """
    base_handler_cls, cb_event_type, event_payload = _require_llamaindex()

    if session is None:
        from ..session import current

        session = current()

    handler_session = session

    # Resolve the CBEventType members we map. Done once at factory time so the
    # per-event hot path is plain comparisons. Members are looked up defensively
    # so a LlamaIndex version missing one of them does not break the handler.
    def _member(name: str) -> Any:
        return getattr(cb_event_type, name, None)

    LLM = _member("LLM")
    FUNCTION_CALL = _member("FUNCTION_CALL")
    AGENT_STEP = _member("AGENT_STEP")
    RETRIEVE = _member("RETRIEVE")

    # EventPayload keys, looked up defensively for the same reason.
    def _payload_key(name: str, default: str) -> Any:
        member = getattr(event_payload, name, None)
        return getattr(member, "value", member) if member is not None else default

    PK_RESPONSE = _payload_key("RESPONSE", "response")
    PK_FUNCTION_CALL = _payload_key("FUNCTION_CALL", "function_call")
    PK_FUNCTION_OUTPUT = _payload_key("FUNCTION_OUTPUT", "function_call_response")
    PK_TOOL = _payload_key("TOOL", "tool")
    PK_QUERY_STR = _payload_key("QUERY_STR", "query_str")
    PK_NODES = _payload_key("NODES", "nodes")
    PK_SERIALIZED = _payload_key("SERIALIZED", "serialized")
    PK_ADDITIONAL_KWARGS = _payload_key("ADDITIONAL_KWARGS", "additional_kwargs")

    def _extract_model(payload: dict[Any, Any]) -> str:
        """Best-effort model identifier from an LLM start payload."""
        try:
            serialized = payload.get(PK_SERIALIZED)
            if isinstance(serialized, dict):
                model = (
                    serialized.get("model")
                    or serialized.get("model_name")
                    or serialized.get("name")
                )
                if isinstance(model, str) and model:
                    return model
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "Promptetheus LlamaIndex adapter failed reading model name",
                exc_info=True,
            )
        return "unknown"

    def _extract_usage(payload: dict[Any, Any]) -> dict[str, int]:
        """Best-effort token usage from an LLM end payload.

        LlamaIndex surfaces raw provider responses (and token counts) on the
        ChatResponse/CompletionResponse raw attribute or in
        additional_kwargs. We probe the common shapes and return only the
        keys we could resolve. Never raises.
        """
        usage: dict[str, int] = {}

        def _coerce(key: str, value: Any) -> None:
            if value is None:
                return
            try:
                usage[key] = int(value)
            except (TypeError, ValueError):
                return

        def _read_usage_mapping(raw_usage: Any) -> None:
            # raw_usage here is already the unwrapped usage container (a dict, or
            # a provider usage object). We avoid the shared extractor's nested
            # usage/usage_metadata unwrapping on purpose: these inputs are the
            # usage object itself, not an outer holder, so we read its alias keys
            # directly. The shared extractor would mis-descend a usage dict that
            # happened to carry its own "usage" key.
            if not isinstance(raw_usage, dict):
                raw_usage = {
                    k: getattr(raw_usage, k, None)
                    for k in (
                        "prompt_tokens",
                        "completion_tokens",
                        "input_tokens",
                        "output_tokens",
                    )
                }
            prompt = (
                raw_usage.get("prompt_tokens")
                if raw_usage.get("prompt_tokens") is not None
                else raw_usage.get("input_tokens")
            )
            completion = (
                raw_usage.get("completion_tokens")
                if raw_usage.get("completion_tokens") is not None
                else raw_usage.get("output_tokens")
            )
            _coerce("input_tokens", prompt)
            _coerce("output_tokens", completion)

        try:
            response = payload.get(PK_RESPONSE)
            if response is not None:
                raw = getattr(response, "raw", None)
                if isinstance(raw, dict):
                    _read_usage_mapping(raw.get("usage"))
                elif raw is not None:
                    _read_usage_mapping(getattr(raw, "usage", None))
                if "input_tokens" not in usage or "output_tokens" not in usage:
                    extra = getattr(response, "additional_kwargs", None)
                    if isinstance(extra, dict):
                        _read_usage_mapping(extra)
            if "input_tokens" not in usage or "output_tokens" not in usage:
                extra = payload.get(PK_ADDITIONAL_KWARGS)
                if isinstance(extra, dict):
                    _read_usage_mapping(extra)
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "Promptetheus LlamaIndex adapter failed reading token usage",
                exc_info=True,
            )

        return usage

    def _tool_name(payload: dict[Any, Any]) -> str:
        """Best-effort tool name from a FUNCTION_CALL/AGENT_STEP payload."""
        try:
            tool = payload.get(PK_TOOL)
            if tool is not None:
                metadata = getattr(tool, "metadata", None)
                name = getattr(metadata, "name", None) or getattr(tool, "name", None)
                if isinstance(name, str) and name:
                    return name
            call = payload.get(PK_FUNCTION_CALL)
            if isinstance(call, dict):
                name = call.get("name")
                if isinstance(name, str) and name:
                    return name
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "Promptetheus LlamaIndex adapter failed reading tool name",
                exc_info=True,
            )
        return "tool"

    def _retrieval_documents(nodes: Any) -> list[dict[str, Any]]:
        """Map LlamaIndex retrieved NodeWithScore objects to plain dicts."""
        documents: list[dict[str, Any]] = []
        try:
            for node_with_score in nodes or []:
                doc: dict[str, Any] = {}
                node = getattr(node_with_score, "node", node_with_score)
                node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
                if node_id is not None:
                    doc["id"] = str(node_id)
                score = getattr(node_with_score, "score", None)
                if score is not None:
                    try:
                        doc["score"] = float(score)
                    except (TypeError, ValueError):
                        pass
                get_content = getattr(node, "get_content", None)
                if callable(get_content):
                    try:
                        content = get_content()
                        if content is not None:
                            doc["content"] = str(content)
                    except Exception:  # pragma: no cover - defensive
                        pass
                documents.append(doc)
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "Promptetheus LlamaIndex adapter failed mapping retrieval nodes",
                exc_info=True,
            )
        return documents

    class _LlamaIndexHandler(base_handler_cls):  # type: ignore[misc, valid-type]
        """LlamaIndex callback handler that emits Promptetheus events.

        Thin by construction: every CBEventType maps to a public Session
        helper, keyed by LlamaIndex's event_id so starts and ends correlate.
        Telemetry failures are logged and swallowed, never raised into the
        observed pipeline.
        """

        def __init__(self) -> None:
            # BaseCallbackHandler requires ignore lists; record everything.
            super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
            self.session = handler_session
            # event_id (str) -> {"start": monotonic seconds, "model": str, ...}
            # Bounded so a long-lived handler cannot accumulate orphaned starts
            # (a start with no matching end, e.g. cancellation) without limit.
            self._pending: BoundedRunState = BoundedRunState(max_size=1024)

        # -- CBEventType dispatch -----------------------------------------

        def on_event_start(
            self,
            event_type: Any,
            payload: Any = None,
            event_id: str = "",
            parent_id: str = "",
            **kwargs: Any,
        ) -> str:
            """Stash per-event start state keyed by event_id.

            Returns the event_id unchanged, as LlamaIndex's
            CallbackManager expects.
            """
            try:
                data = _as_dict(payload)
                if event_type == LLM:
                    self._stash(
                        event_id,
                        {"start": time.monotonic(), "model": _extract_model(data)},
                    )
                elif event_type in (FUNCTION_CALL, AGENT_STEP):
                    self._emit_tool_call(event_id, data)
                elif event_type == RETRIEVE:
                    self._stash(
                        event_id,
                        {"query": self._query_str(data)},
                    )
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception(
                    "Promptetheus LlamaIndex adapter failed on_event_start"
                )
            return event_id or ""

        def on_event_end(
            self,
            event_type: Any,
            payload: Any = None,
            event_id: str = "",
            **kwargs: Any,
        ) -> None:
            """Emit the terminal Promptetheus event for event_id."""
            try:
                data = _as_dict(payload)
                if event_type == LLM:
                    self._emit_llm_call(event_id, data)
                elif event_type in (FUNCTION_CALL, AGENT_STEP):
                    self._emit_tool_result(event_id, data)
                elif event_type == RETRIEVE:
                    self._emit_retrieval(event_id, data)
            except Exception:  # pragma: no cover - helpers already swallow
                logger.exception("Promptetheus LlamaIndex adapter failed on_event_end")

        # -- Trace lifecycle (no-ops; required by BaseCallbackHandler) ----

        def start_trace(self, trace_id: str | None = None) -> None:
            """No-op: Promptetheus owns its own session/trace lifecycle."""
            return None

        def end_trace(
            self,
            trace_id: str | None = None,
            trace_map: dict[str, list[str]] | None = None,
        ) -> None:
            """No-op: Promptetheus owns its own session/trace lifecycle."""
            return None

        # -- emission helpers ---------------------------------------------

        def _emit_llm_call(self, event_id: str, payload: dict[Any, Any]) -> None:
            run = self._pending.pop(_event_key(event_id), None)
            model = (run or {}).get("model") or _extract_model(payload)
            latency_ms: int | None = None
            started = (run or {}).get("start")
            if started is not None:
                latency_ms = int((time.monotonic() - started) * 1000)
            usage = _extract_usage(payload)
            self.session.llm_call(
                model,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                latency_ms=latency_ms,
                metadata={"event_id": _event_key(event_id)},
            )

        def _emit_tool_call(self, event_id: str, payload: dict[Any, Any]) -> None:
            arguments: dict[str, Any] = {}
            call = payload.get(PK_FUNCTION_CALL)
            if isinstance(call, dict):
                arguments = dict(call)
            elif call is not None:
                arguments = {"input": str(call)}
            self.session.tool_call(
                tool_name=_tool_name(payload),
                arguments=arguments,
                call_id=_event_key(event_id),
            )

        def _emit_tool_result(self, event_id: str, payload: dict[Any, Any]) -> None:
            output = payload.get(PK_FUNCTION_OUTPUT)
            if output is None:
                output = payload.get(PK_RESPONSE)
            self.session.tool_result(
                call_id=_event_key(event_id),
                result=None if output is None else str(output),
            )

        def _emit_retrieval(self, event_id: str, payload: dict[Any, Any]) -> None:
            run = self._pending.pop(_event_key(event_id), None)
            query = (run or {}).get("query") or self._query_str(payload)
            nodes = payload.get(PK_NODES)
            self.session.retrieval(
                query=query,
                documents=_retrieval_documents(nodes),
                metadata={"event_id": _event_key(event_id)},
            )

        # -- internal ------------------------------------------------------

        def _query_str(self, payload: dict[Any, Any]) -> str:
            query = payload.get(PK_QUERY_STR)
            return str(query) if query is not None else ""

        def _stash(self, event_id: str, value: dict[str, Any]) -> None:
            # BoundedRunState.set evicts the oldest entry when the cap is hit, so
            # orphaned starts cannot accumulate without bound.
            self._pending.set(_event_key(event_id), value)

    return _LlamaIndexHandler()


__all__ = ["LlamaIndexAdapter"]
