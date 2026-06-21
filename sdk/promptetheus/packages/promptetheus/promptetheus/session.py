"""Session primitives for Promptetheus instrumentation."""

from __future__ import annotations

import contextvars
import functools
import hashlib
import inspect
import logging
import os
import threading
import time
import traceback as _traceback
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Iterator, Mapping, MutableMapping, ParamSpec, TypeVar

try:  # schema.py is created by the contract workstream; keep import-time light.
    from .schema import validate_event
except Exception:  # pragma: no cover - defensive during partial installs
    validate_event = None  # type: ignore[assignment]

from .sampling import DEFAULT_TAIL_POLICY, TailSamplingPolicy

logger = logging.getLogger("promptetheus")

# Event types never dropped by per-event-type sampling: session lifecycle and
# failure signals, plus span markers (dropping a span_start/span_end would break
# the run tree).
_ALWAYS_KEEP_TYPES = frozenset({"session_end", "error", "goal_check", "state_change"})

P = ParamSpec("P")
R = TypeVar("R")

_current_session: contextvars.ContextVar["Session | None"] = contextvars.ContextVar(
    "promptetheus_current_session",
    default=None,
)

# Per-session stack of active span ids. Stored in a ContextVar so the active
# span is correct across threads and async tasks: each Session reads and writes
# only its own entry, keyed by session_id. The value is a mapping from
# session_id to a tuple acting as an immutable stack (top is the last element);
# we always replace the whole mapping/tuple so concurrent contexts never share
# mutable state.
_span_stacks: contextvars.ContextVar[Mapping[str, tuple[str, ...]]] = (
    contextvars.ContextVar(
        "promptetheus_span_stacks",
        default={},
    )
)


def _new_span_id() -> str:
    return f"span_{uuid.uuid4().hex}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _new_ulid() -> str:
    """Mint a Crockford-base32 ULID (26 chars) for session_id."""

    timestamp_ms = int(time.time() * 1000)
    randomness = int.from_bytes(os.urandom(10), "big")

    def _encode(value: int, length: int) -> str:
        chars = ["0"] * length
        for i in range(length - 1, -1, -1):
            chars[i] = _CROCKFORD[value & 0x1F]
            value >>= 5
        return "".join(chars)

    return _encode(timestamp_ms, 10) + _encode(randomness, 16)


def _new_session_id() -> str:
    return _new_ulid()


def _new_nonce() -> str:
    return uuid.uuid4().hex[:8]


def _should_record(session_id: str, sample_rate: float) -> bool:
    """Decide deterministically whether a whole session is recorded.

    Sampling is per-session (never per-event) so a recorded session keeps full
    timeline integrity. The decision hashes session_id into [0, 1) and
    records when that fraction is below sample_rate. sample_rate >= 1.0
    always records (default); <= 0.0 never does.
    """

    if sample_rate >= 1.0:
        return True
    if sample_rate <= 0.0:
        return False
    digest = hashlib.sha256(session_id.encode("utf-8")).digest()[:8]
    fraction = int.from_bytes(digest, "big") / float(1 << 64)
    return fraction < sample_rate


def _resolve_redact(
    redact: Any,
) -> Callable[[MutableMapping[str, Any]], MutableMapping[str, Any] | None] | None:
    """Resolve the redact argument into a callable (or None).

    Accepts a callable (used as-is), the string "default" (the built-in
    secret/PII redactor), or None / an unknown string (no redaction).
    """

    if redact is None:
        return None
    if callable(redact):
        return redact
    if isinstance(redact, str) and redact == "default":
        from .redaction import build_default_redactor

        return build_default_redactor()
    return None


class NoopSession:
    """Null object returned by current() when no Promptetheus session is active."""

    session_id = "noop"

    def event(
        self,
        type: str,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        return None

    def flush(self, timeout: float | None = None) -> None:
        return None

    def end(self, status: str = "completed", error: str | None = None) -> None:
        return None

    @contextmanager
    def span(
        self, name: str, metadata: Mapping[str, Any] | None = None
    ) -> Iterator[None]:
        # No active session: the span is a no-op but still usable as a context
        # manager so call sites do not have to special-case current().
        yield None

    def __getattr__(self, name: str) -> Callable[..., None]:
        def _noop(*args: Any, **kwargs: Any) -> None:
            return None

        return _noop


class Session:
    """A single observed agent run.

    The session stamps the event envelope, validates it when the schema module is
    present, and hands batches to the configured transport. Transport failures
    are logged and swallowed so observed agents do not crash because telemetry is
    unavailable.
    """

    def __init__(
        self,
        *,
        agent: str,
        user_goal: str,
        session_id: str | None = None,
        project_id: str | None = None,
        environment: str | None = None,
        transport: Any | None = None,
        redact: Callable[[MutableMapping[str, Any]], MutableMapping[str, Any] | None]
        | str
        | None = None,
        metadata: Mapping[str, Any] | None = None,
        tags: list[str] | None = None,
        sample_rate: float = 1.0,
        tail_sample: bool = False,
        event_sample_rates: Mapping[str, float] | None = None,
        tail_policy: TailSamplingPolicy | None = None,
    ) -> None:
        self.agent = agent
        self.user_goal = user_goal
        self.session_id = session_id or _new_session_id()
        self.project_id = project_id
        self.environment = environment
        self.metadata = dict(metadata or {})
        self.tags = list(tags or [])
        self._transport = transport
        self._redact = _resolve_redact(redact)
        # Per-session sampling decision: a sampled-out session runs the user's
        # code normally but emits nothing (whole-session integrity).
        self.sample_rate = sample_rate
        self._record = _should_record(self.session_id, sample_rate)
        self._nonce = _new_nonce()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._ended = False
        self._terminal_event: dict[str, Any] | None = None
        self._ctx_token: contextvars.Token[Session | None] | None = None
        # Tail-based sampling. When enabled, events are buffered in memory rather
        # than sent immediately; on end()/__exit__ the session keeps the whole
        # buffer if it looks interesting (a failure of any kind) and otherwise
        # applies the head sample_rate to decide keep-or-drop for a boring
        # success. Default tail_sample=False preserves immediate-send behavior.
        self.tail_sample = tail_sample
        self._buffer: list[dict[str, Any]] = []
        # Set once any failure signal is observed during the run; forces a flush
        # of the buffered timeline regardless of head sample_rate.
        self._tail_interesting = False
        self._tail_flushed = False
        # The policy that turns the buffered timeline into a keep-or-drop verdict
        # at end(). Defaults to a policy whose boring keep-rate defers to the head
        # sample_rate, so a plain tail_sample=True behaves exactly as before.
        self._tail_policy = tail_policy or DEFAULT_TAIL_POLICY
        # Optional per-event-type keep probabilities (e.g. sample noisy
        # dom_snapshots while keeping everything else). Types not listed are kept;
        # lifecycle/failure/span types are always kept. Decision is deterministic
        # per event so it is reproducible.
        self._event_sample_rates = {
            str(k): float(v) for k, v in (event_sample_rates or {}).items()
        }

    def _keep_for_type_sampling(self, event: Mapping[str, Any]) -> bool:
        """Per-event-type sampling: should this event be recorded at all?

        Returns True unless the event's type has a configured keep-rate below 1.0
        and this event falls outside it (decided deterministically by its
        idempotency key). Lifecycle, failure, and span-marker types are always
        kept so the timeline and run tree stay coherent.
        """

        if not self._event_sample_rates:
            return True
        etype = str(event.get("type"))
        if etype in _ALWAYS_KEEP_TYPES:
            return True
        rate = self._event_sample_rates.get(etype)
        if rate is None or rate >= 1.0:
            return True
        if rate <= 0.0:
            return False
        digest = hashlib.sha256(
            str(event.get("idempotency_key")).encode("utf-8")
        ).digest()[:8]
        fraction = int.from_bytes(digest, "big") / float(1 << 64)
        return fraction < rate

    def _span_stack(self) -> tuple[str, ...]:
        """Return this session's current span-id stack (top is the last element)."""

        return _span_stacks.get().get(self.session_id, ())

    def _push_span(
        self, span_id: str
    ) -> contextvars.Token[Mapping[str, tuple[str, ...]]]:
        """Push span_id onto this session's stack; return a token to restore it."""

        stacks = _span_stacks.get()
        new_stack = stacks.get(self.session_id, ()) + (span_id,)
        new_stacks = dict(stacks)
        new_stacks[self.session_id] = new_stack
        return _span_stacks.set(new_stacks)

    def _current_span_ids(self) -> tuple[str | None, str | None]:
        """Return (span_id, parent_id) for the active span, or (None, None).

        span_id is the top of this session's stack; parent_id is the entry
        beneath it (None when the active span is top-level, and both None when no
        span is active so events stay flat exactly as before).
        """

        stack = self._span_stack()
        if not stack:
            return None, None
        span_id = stack[-1]
        parent_id = stack[-2] if len(stack) >= 2 else None
        return span_id, parent_id

    @contextmanager
    def span(
        self, name: str, metadata: Mapping[str, Any] | None = None
    ) -> Iterator[str]:
        """Open a run-tree span around a block of work.

        Mints a new span_id, records parent_id from the current top-of-stack span
        (or None at the top level), pushes the new span, and emits a state_change
        event named span_start carrying the span name. Every event emitted inside
        the block is stamped with this span_id and parent_id. On exit it emits a
        span_end state_change and pops the span. Yields the new span_id.

        Spans nest: opening a span inside another makes the inner span's parent_id
        the outer span's id. With no active span, behavior is unchanged and events
        carry no span_id/parent_id.
        """

        span_id = _new_span_id()
        token = self._push_span(span_id)
        # Wall-clock start captured from a monotonic source so the span_end
        # duration_ms is immune to system clock adjustments during the block.
        started_at = time.monotonic()
        try:
            self.event(
                "state_change",
                {"name": "span_start", "span_name": name},
                metadata,
            )
            yield span_id
        finally:
            try:
                duration_ms = int(round((time.monotonic() - started_at) * 1000))
                self.event(
                    "state_change",
                    {"name": "span_end", "span_name": name, "duration_ms": duration_ms},
                    metadata,
                )
            finally:
                _span_stacks.reset(token)

    def _create_trace(self) -> None:
        """Tell the transport to open the trace record for this session.

        In immediate mode this fires from __enter__. In tail-sample mode it is
        deferred to _resolve_tail and only fires when the session is kept, so a
        dropped boring success creates no server-side trace.
        """

        try:
            if self._transport is not None and hasattr(self._transport, "create_trace"):
                self._transport.create_trace(
                    {
                        "id": self.session_id,
                        "agent": self.agent,
                        "user_goal": self.user_goal,
                        "project_id": self.project_id,
                        "environment": self.environment,
                        "metadata": self.metadata,
                        "tags": self.tags,
                    }
                )
        except Exception:
            logger.exception("Promptetheus transport failed while creating trace")

    def __enter__(self) -> "Session":
        self._ctx_token = _current_session.set(self)
        # In tail-sample mode trace creation is deferred until the keep decision
        # at end()/_resolve_tail; here we only create eagerly for immediate mode.
        if self._record and not self.tail_sample:
            self._create_trace()
        self.event(
            "state_change",
            {
                "name": "session_started",
                "before": None,
                "after": {
                    "agent": self.agent,
                    "user_goal": self.user_goal,
                    "project_id": self.project_id,
                    "environment": self.environment,
                    "tags": self.tags,
                },
            },
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if not self._ended:
            if exc is None:
                self.end("completed")
            else:
                self.end(
                    "failed",
                    error=f"{exc_type.__name__ if exc_type else 'Error'}: {exc}",
                )
        self.flush()
        if self._ctx_token is not None:
            _current_session.reset(self._ctx_token)
            self._ctx_token = None

    def event(
        self,
        type: str,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._seq_lock:
            seq = self._seq
            self._seq += 1

        event: dict[str, Any] = {
            "type": type,
            "session_id": self.session_id,
            "timestamp": _utc_now(),
            "seq": seq,
            "idempotency_key": f"{self.session_id}:{self._nonce}:{seq}",
            "payload": dict(payload or {}),
        }
        if metadata:
            event["metadata"] = dict(metadata)

        # Stamp run-tree fields when a span is active. With no active span both
        # are None and we add neither key, so the event stays flat exactly as
        # before.
        span_id, parent_id = self._current_span_ids()
        if span_id is not None:
            event["span_id"] = span_id
            event["parent_id"] = parent_id

        should_deliver = True

        if self._redact is not None:
            try:
                redacted = self._redact(event)
            except Exception:
                logger.exception(
                    "Promptetheus redactor failed; dropping event to avoid emitting unredacted data"
                )
                should_deliver = False
            else:
                if redacted is not None:
                    event = dict(redacted)

        if validate_event is not None:
            try:
                validate_event(event)
            except Exception:
                logger.exception(
                    "Promptetheus event validation failed; dropping invalid event"
                )
                should_deliver = False

        # Note whether this event is a failure signal so tail sampling can decide
        # to keep the whole session.
        if self.tail_sample:
            self._note_tail_signal(event)

        # Per-event-type sampling: drop sampled-out noise types (the event dict is
        # still returned to the caller, but it is neither buffered nor sent).
        if not self._keep_for_type_sampling(event):
            return event
        if not should_deliver:
            return event

        try:
            if self.tail_sample:
                # Always buffer; the head sample_rate is applied to the whole
                # session at end() in _resolve_tail, so per-event _record gating
                # must not drop events here.
                if self._transport is not None:
                    self._buffer.append(event)
            elif self._record and self._transport is not None:
                if hasattr(self._transport, "send_event"):
                    self._transport.send_event(event)
                elif hasattr(self._transport, "send_batch"):
                    self._transport.send_batch([event])
        except Exception:
            logger.exception("Promptetheus transport failed while sending event")

        return event

    def _note_tail_signal(self, event: Mapping[str, Any]) -> None:
        """Mark the session interesting if event is a failure signal.

        Interesting means: a goal_check that did not pass, or a session_end with
        a non-completed status or an error. Once interesting, tail sampling
        flushes the whole buffered timeline regardless of head sample_rate.
        """

        event_type = event.get("type")
        payload = event.get("payload") or {}
        if event_type == "goal_check" and payload.get("passed") is False:
            self._tail_interesting = True
        elif event_type == "session_end":
            status = payload.get("status")
            if (status is not None and status != "completed") or payload.get("error"):
                self._tail_interesting = True

    def user_message(
        self, content: str, metadata: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return self.event("user_message", {"content": content}, metadata)

    def agent_message(
        self, content: str, metadata: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return self.event("agent_message", {"content": content}, metadata)

    def tool_call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        call_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.event(
            "tool_call",
            {
                "tool_name": tool_name,
                "arguments": dict(arguments or {}),
                "call_id": call_id or uuid.uuid4().hex,
            },
            metadata,
        )

    def tool_result(
        self,
        call_id: str,
        result: Any = None,
        error: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.event(
            "tool_result",
            {"call_id": call_id, "result": result, "error": error},
            metadata,
        )

    def retrieval(
        self,
        query: str,
        documents: list[Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.event(
            "retrieval", {"query": query, "documents": documents}, metadata
        )

    def browser_action(
        self,
        action: str,
        target: str,
        url: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.event(
            "browser_action", {"action": action, "target": target, "url": url}, metadata
        )

    def dom_snapshot(
        self,
        url: str,
        visible_text: str,
        selected_values: Mapping[str, Any] | None = None,
        warnings: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.event(
            "dom_snapshot",
            {
                "url": url,
                "visible_text": visible_text,
                "selected_values": dict(selected_values or {}),
                "warnings": list(warnings or []),
            },
            metadata,
        )

    def _artifact_bytes(self, source: bytes | str) -> tuple[bytes, str] | None:
        """Read artifact bytes when available; None for path-only references."""

        if isinstance(source, bytes):
            return source, "artifact.bin"
        try:
            path = Path(source)
            if not path.is_file():
                return None
            return path.read_bytes(), path.name
        except (OSError, ValueError):
            logger.exception("Promptetheus failed to read artifact path")
            return None

    def _upload_artifact(
        self,
        *,
        body: bytes,
        content_type: str,
        filename: str,
        artifact_type: str | None = None,
    ) -> dict[str, str] | None:
        if self._transport is None:
            return None
        uploader = getattr(self._transport, "upload_artifact", None)
        if not callable(uploader):
            return None
        try:
            result = uploader(
                self.session_id,
                body=body,
                content_type=content_type,
                filename=filename,
                artifact_type=artifact_type,
            )
        except Exception:
            logger.exception("Promptetheus transport failed while uploading artifact")
            return None
        if not isinstance(result, Mapping):
            return None
        artifact_id = result.get("artifact_id")
        storage_path = result.get("storage_path")
        if not artifact_id or not storage_path:
            return None
        return {
            "artifact_id": str(artifact_id),
            "storage_path": str(storage_path),
        }

    def screenshot(
        self, source: bytes | str, metadata: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        artifact_data = self._artifact_bytes(source)
        payload: dict[str, Any] = {}
        if artifact_data is not None:
            body, filename = artifact_data
            if not filename.lower().endswith(".png"):
                filename = f"{Path(filename).stem}.png"
            payload["size_bytes"] = len(body)
            if isinstance(source, bytes):
                payload["source_type"] = "bytes"
            identity = self._upload_artifact(
                body=body,
                content_type="image/png",
                filename=filename,
                artifact_type="screenshot",
            )
            if identity:
                payload.update(identity)
            elif isinstance(source, str):
                payload["source"] = source
        elif isinstance(source, str):
            payload["source"] = source
        return self.event("screenshot", payload, metadata)

    def replay_artifact(
        self,
        source: str | bytes,
        artifact_type: str = "screen_recording",
        event_time_map: Mapping[str, int] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact_data = self._artifact_bytes(source)
        payload: dict[str, Any] = {
            "artifact_type": artifact_type,
            "event_time_map": dict(event_time_map or {}),
        }
        if artifact_data is not None:
            body, filename = artifact_data
            if not filename.lower().endswith(".webm"):
                filename = f"{Path(filename).stem}.webm"
            payload["size_bytes"] = len(body)
            identity = self._upload_artifact(
                body=body,
                content_type="video/webm",
                filename=filename,
                artifact_type="replay",
            )
            if identity:
                payload.update(identity)
            elif isinstance(source, str):
                payload["source"] = str(source)
        elif isinstance(source, str):
            payload["source"] = str(source)
        return self.event("replay_artifact", payload, metadata)

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
        """Record an LLM invocation (model, token usage, latency).

        First consumed by the LLM/framework adapters (OpenAI, Anthropic,
        LangChain). Carries references to prompt/messages rather than raw content
        so adapters can keep large or sensitive payloads out of the event stream.
        """
        payload: dict[str, Any] = {"model": model}
        if input_tokens is not None:
            payload["input_tokens"] = input_tokens
        if output_tokens is not None:
            payload["output_tokens"] = output_tokens
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        if messages_ref is not None:
            payload["messages_ref"] = messages_ref
        if prompt_ref is not None:
            payload["prompt_ref"] = prompt_ref
        return self.event("llm_call", payload, metadata)

    def goal_check(
        self,
        passed: bool,
        mismatches: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.event(
            "goal_check",
            {"passed": passed, "mismatches": list(mismatches or [])},
            metadata,
        )

    def score(
        self,
        name: str,
        value: float | int | bool,
        comment: str | None = None,
        source: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Attach a score / feedback to the run (human rating or automated check).

        value is a number or bool; source distinguishes e.g. human from auto.
        """
        payload: dict[str, Any] = {"name": name, "value": value}
        if comment is not None:
            payload["comment"] = comment
        if source is not None:
            payload["source"] = source
        return self.event("score", payload, metadata)

    def error(
        self,
        error: BaseException | str,
        *,
        error_type: str | None = None,
        handled: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an error/exception with a captured traceback.

        Accepts an exception (its message, type, and formatted traceback are
        captured) or a plain string message. Richer than a tool_result error.
        """
        payload: dict[str, Any] = {"handled": handled}
        if isinstance(error, BaseException):
            payload["message"] = str(error)
            payload["error_type"] = error_type or type(error).__name__
            tb = "".join(
                _traceback.format_exception(type(error), error, error.__traceback__)
            )
            if tb.strip():
                payload["traceback"] = tb
        else:
            payload["message"] = str(error)
            if error_type is not None:
                payload["error_type"] = error_type
        return self.event("error", payload, metadata)

    def metric(
        self,
        name: str,
        value: float | int,
        unit: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Emit an arbitrary numeric metric during the run."""
        payload: dict[str, Any] = {"name": name, "value": value}
        if unit is not None:
            payload["unit"] = unit
        return self.event("metric", payload, metadata)

    def update_metadata(self, **values: Any) -> dict[str, Any]:
        """Merge keys into the session metadata and record the change.

        Updates the in-memory session metadata and emits a state_change so the
        update is part of the timeline.
        """
        self.metadata.update(values)
        return self.event(
            "state_change",
            {"name": "metadata_update", "before": None, "after": dict(values)},
        )

    def add_tags(self, *tags: str) -> dict[str, Any]:
        """Append tags to the session and record the change in the timeline.

        Skips tags already present and de-duplicates within this call.
        """
        new: list[str] = []
        for tag in tags:
            if tag not in self.tags and tag not in new:
                new.append(tag)
        self.tags.extend(new)
        return self.event(
            "state_change",
            {"name": "tags_added", "before": None, "after": {"tags": new}},
        )

    def state_change(
        self,
        name: str,
        before: Any = None,
        after: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.event(
            "state_change", {"name": name, "before": before, "after": after}, metadata
        )

    def end(
        self, status: str = "completed", error: str | None = None
    ) -> dict[str, Any]:
        if self._terminal_event is not None:
            return self._terminal_event
        self._ended = True
        event = self.event("session_end", {"status": status, "error": error})
        self._terminal_event = event
        if self.tail_sample:
            self._resolve_tail()
        self.flush()
        return event

    def _resolve_tail(self) -> None:
        """Make the tail-sampling keep-or-drop decision for the buffered session.

        Called once at end(). If the session is interesting (a failure of any
        kind: status not completed, an exception, a failed goal_check, or a
        session_end carrying an error) the whole buffer is flushed to the
        transport. Otherwise this is a boring success and the head sample_rate
        decides keep-or-drop for the entire session. Either way the flush is
        all-or-nothing, preserving whole-session integrity.
        """

        if self._tail_flushed:
            return
        self._tail_flushed = True

        buffered = self._buffer
        self._buffer = []
        if not buffered:
            return

        decision = self._tail_policy.decide(
            buffered,
            session_id=self.session_id,
            head_sample_rate=self.sample_rate,
        )
        # A failure signal noticed incrementally during the run also forces keep,
        # belt-and-suspenders alongside the policy's own scan of the buffer.
        keep = decision.keep or self._tail_interesting

        if not keep:
            if self._tail_policy.emit_skeleton_on_drop:
                self._flush_drop_skeleton(buffered, decision.reason)
            return

        # We are keeping this session: open the trace record now (deferred from
        # __enter__ for tail mode) before flushing its buffered timeline.
        self._create_trace()
        self._send_buffered(buffered)

    def _send_buffered(self, buffered: list[dict[str, Any]]) -> None:
        """Send a list of buffered events via whichever transport API exists."""
        try:
            if self._transport is None:
                return
            if hasattr(self._transport, "send_batch"):
                self._transport.send_batch(buffered)
            elif hasattr(self._transport, "send_event"):
                for event in buffered:
                    self._transport.send_event(event)
        except Exception:
            logger.exception("Promptetheus transport failed while flushing tail buffer")

    def _flush_drop_skeleton(self, buffered: list[dict[str, Any]], reason: str) -> None:
        """Emit a minimal skeleton for a dropped session.

        Sends the session's opening event and its session_end so downstream still
        sees that the run happened, annotating the session_end with the drop
        reason and how many events were elided. Opt-in via the policy; the default
        keeps the original all-or-nothing drop.
        """

        if not buffered:
            return
        opening = buffered[0]
        end_event = next(
            (e for e in reversed(buffered) if e.get("type") == "session_end"),
            buffered[-1],
        )
        skeleton_end = dict(end_event)
        payload = dict(skeleton_end.get("payload") or {})
        payload["tail_dropped"] = True
        payload["tail_drop_reason"] = reason
        payload["tail_dropped_event_count"] = len(buffered)
        skeleton_end["payload"] = payload
        self._create_trace()
        skeleton = [opening] if opening is end_event else [opening, skeleton_end]
        self._send_buffered(skeleton)

    def flush(self, timeout: float | None = None) -> None:
        try:
            if self._transport is not None and hasattr(self._transport, "flush"):
                self._transport.flush(timeout=timeout)
        except TypeError:
            try:
                if self._transport is not None:
                    self._transport.flush()
            except Exception:
                logger.exception("Promptetheus transport failed while flushing")
        except Exception:
            logger.exception("Promptetheus transport failed while flushing")


def current() -> Session | NoopSession:
    return _current_session.get() or NoopSession()


def _make_wrapper(
    func: Callable[P, R],
    enter: Callable[[], Any],
    on_call: Callable[[Any, tuple[Any, ...], dict[str, Any]], Any],
    on_result: Callable[[Any, Any, R], None],
    on_error: Callable[[Any, Any, BaseException], None],
) -> Callable[P, R]:
    """Build one sync-or-async wrapper shared by observe, tool, and traced.

    This is the single wrapping path the three decorators delegate to so the
    start / call / record / handle-exception / end boilerplate exists once. The
    callbacks parameterize the per-decorator differences:

    enter() returns a context manager that is entered for the duration of the
    call (a fresh Session for observe, current().span(...) for traced, or a
    trivial null context for tool). Its entered value is passed to the other
    callbacks as ctx.

    on_call(ctx, args, kwargs) runs before the wrapped function and returns a
    per-call token (for example the tool_call call_id) handed back to on_result
    and on_error. on_result(ctx, token, result) runs after a successful call;
    on_error(ctx, token, exc) runs when the call raises, before the exception is
    re-raised. Any of these may be a no-op.

    The sync and async branches are mirror images: both honor every option baked
    into enter() (for observe that means sample_rate, redact, tail_sample, and
    event_sample_rates, since those live on the Session that enter() creates) and
    both record results and exceptions identically.
    """

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def _async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with enter() as ctx:
                token = on_call(ctx, args, kwargs)
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    on_error(ctx, token, exc)
                    raise
                on_result(ctx, token, result)
                return result

        # functools.wraps on an async def yields a _Wrapped type mypy cannot
        # reconcile with Callable[P, R]; the runtime behavior is correct.
        return _async_wrapper  # type: ignore[return-value]

    @functools.wraps(func)
    def _wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with enter() as ctx:
            token = on_call(ctx, args, kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                on_error(ctx, token, exc)
                raise
            on_result(ctx, token, result)
            return result

    return _wrapper


def observe(
    *,
    agent: str | None = None,
    user_goal: str,
    project_id: str | None = None,
    api_key: str | None = None,
    environment: str | None = None,
    transport: Any | None = None,
    endpoint: str | None = None,
    spool_dir: str = ".promptetheus/spool",
    redact: Callable[[MutableMapping[str, Any]], MutableMapping[str, Any] | None]
    | str
    | None = None,
    metadata: Mapping[str, Any] | None = None,
    tags: list[str] | None = None,
    sample_rate: float | None = None,
    tail_sample: bool = False,
    event_sample_rates: Mapping[str, float] | None = None,
    tail_policy: TailSamplingPolicy | None = None,
    **_: Any,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Observe a function as a Promptetheus session.

    sample_rate and redact fall back to ~/.promptetheus/config.toml /
    env config when left as None (see .config). redact="default"
    enables the built-in secret/PII redactor.

    tail_sample is opt-in (default False keeps immediate-send behavior). When
    True, events are buffered and the whole session is kept only if it is
    interesting (a failure of any kind); otherwise sample_rate decides keep-or-
    drop for the boring success as an all-or-nothing flush.
    """

    def _decorator(func: Callable[P, R]) -> Callable[P, R]:
        from .config import get_config
        from .trace import resolve_transport

        session_agent = agent or func.__name__
        _cfg = get_config()
        _sample_rate = _cfg.sample_rate if sample_rate is None else sample_rate
        _redact = _cfg.redact if redact is None else redact

        def _enter() -> Session:
            # A fresh Session per call. Every sampling/redaction option is set
            # here, so both the sync and async branches of _make_wrapper honor
            # sample_rate, redact, tail_sample, and event_sample_rates identically
            # (a past bug had the sync path silently drop these).
            return Session(
                agent=session_agent,
                user_goal=user_goal,
                project_id=project_id,
                environment=environment,
                transport=resolve_transport(
                    transport, endpoint=endpoint, api_key=api_key, spool_dir=spool_dir
                ),
                redact=_redact,
                metadata=metadata,
                tags=tags,
                sample_rate=_sample_rate,
                tail_sample=tail_sample,
                event_sample_rates=event_sample_rates,
                tail_policy=tail_policy,
            )

        def _on_call(
            session: Session, args: tuple[Any, ...], kwargs: dict[str, Any]
        ) -> str:
            call_id = uuid.uuid4().hex
            session.tool_call(
                func.__name__,
                {"args": repr(args), "kwargs": repr(kwargs)},
                call_id=call_id,
            )
            return call_id

        def _on_result(session: Session, call_id: str, result: R) -> None:
            session.tool_result(call_id, result=repr(result))

        def _on_error(session: Session, call_id: str, exc: BaseException) -> None:
            session.tool_result(call_id, error=repr(exc))

        return _make_wrapper(func, _enter, _on_call, _on_result, _on_error)

    return _decorator


@contextmanager
def _current_session_context() -> Iterator[Session | NoopSession]:
    """Resolve the active session per call and yield it as the wrapper context.

    Mirrors the original tool() behavior of calling current() at call time so a
    tool decorated before a session opens still records into whatever session is
    active when it actually runs.
    """

    yield current()


def tool(func: Callable[P, R]) -> Callable[P, R]:
    """Record a function call as a tool_call/tool_result when a session is active."""

    def _on_call(
        session: Session | NoopSession, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> str:
        call_id = uuid.uuid4().hex
        session.tool_call(
            func.__name__, {"args": repr(args), "kwargs": repr(kwargs)}, call_id=call_id
        )
        return call_id

    def _on_result(session: Session | NoopSession, call_id: str, result: R) -> None:
        session.tool_result(call_id, result=repr(result))

    def _on_error(
        session: Session | NoopSession, call_id: str, exc: BaseException
    ) -> None:
        session.tool_result(call_id, error=repr(exc))

    return _make_wrapper(
        func, _current_session_context, _on_call, _on_result, _on_error
    )


def traced(name: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that runs a function inside a current-session run-tree span.

    Opens current().span(name or func.__name__) around each call so the
    function's events nest under a span. A no-op when no session is active.
    Works on sync and async functions. Use it to give a multi-step helper its own
    node in the trace tree without a with-block:

        @traced("retrieve")
        def retrieve(q): ...
    """

    def _decorator(func: Callable[P, R]) -> Callable[P, R]:
        span_name = name or func.__name__

        def _enter() -> Any:
            # current() is resolved per call, exactly as before, so a function
            # decorated before any session opens still nests under whatever
            # session is active when it runs (a no-op span when none is).
            return current().span(span_name)

        def _noop_call(ctx: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
            return None

        def _noop_result(ctx: Any, token: Any, result: R) -> None:
            return None

        def _noop_error(ctx: Any, token: Any, exc: BaseException) -> None:
            return None

        return _make_wrapper(func, _enter, _noop_call, _noop_result, _noop_error)

    return _decorator
