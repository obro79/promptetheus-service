"""Durable HTTP transport: reliable, non-blocking event delivery (P8).

This is the SDK's production delivery layer. It wraps the low-level synchronous
HTTPTransport poster and adds:

- non-blocking send_event / send_batch via a *bounded* in-memory queue
  that spills overflow to the spool instead of blocking or dropping silently,
- a single daemon background flusher that batches and POSTs to FastAPI,
- exponential backoff retry on transient failures (network, 5xx, 429),
- a local JSONL spool (with a configurable size cap) for batches that exhaust
  their retries; oldest replayable files are pruned first on overflow,
- spool replay on flush/startup (safe because the server dedupes on
  idempotency_key),
- per-event dead-lettering driven by the batch response
  {accepted, rejected: [{index, idempotency_key, reason}]} and by permanent
  4xx whole-request rejections.

Hard guarantees:

- Instrumentation never raises into the host agent. Every transport failure is
  logged via the promptetheus logger and swallowed or spooled.
- Canonical product storage is never written directly; failed deliveries are
  spooled locally and replayed through FastAPI only.
- Dependency-light: stdlib only (threading, queue, json, pathlib,
  urllib via the wrapped poster).
"""

from __future__ import annotations

import atexit
import gzip
import json
import logging
import os
import queue
import random
import re
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request

from . import BaseTransport, Event
from . import http as _http
from .http import HTTPTransport

logger = logging.getLogger("promptetheus")

_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
_DEAD_LETTER_DIR = "dead-letter"

# Default request-body size (in bytes of UTF-8 JSON) at or above which the
# durable transport gzip-compresses the POST body and sets Content-Encoding:
# gzip. Bodies smaller than this are sent uncompressed because the gzip header
# overhead and CPU cost are not worth it for tiny payloads. Opt-in tuning is via
# the compress_min_bytes constructor argument; pass 0 to disable compression.
_DEFAULT_COMPRESS_MIN_BYTES = 1024

# Backoff window bounds. The exponential schedule is 0.5 * 2**attempt seconds,
# capped at _BACKOFF_CAP. Each wait is randomized within [0, window) (full
# jitter) so many retrying clients do not wake in lockstep and stampede the
# server. _BACKOFF_BASE and _BACKOFF_CAP keep the schedule explicit and testable.
_BACKOFF_BASE = 0.5
_BACKOFF_CAP = 30.0
_SPOOL_REPLAY_FAILURE_COOLDOWN = 30.0

# HTTP status codes that are permanent client errors: never retry, dead-letter
# the whole request immediately.
_PERMANENT_STATUS = frozenset({400, 401, 403, 404, 415, 422})

# Other non-retryable 4xx that are genuinely safe to drop without a forensic
# record (the server already has the data or there is nothing to keep). Anything
# else in the 4xx range is dead-lettered rather than silently dropped.
_SAFE_DROP_STATUS = frozenset({409})
_REPLAYING_MARKER = ".replaying-"


# Sentinel pushed onto the queue to wake the flusher for a synchronous drain.
# Carries the flush generation it belongs to so flush() can wait for the
# specific drain it requested instead of a shared idle flag.
class _FlushSentinel:
    __slots__ = ("generation",)

    def __init__(self, generation: int) -> None:
        self.generation = generation


class _AcceptRejectOutcome:
    __slots__ = ("accepted", "rejected", "retryable", "fully_accounted")

    def __init__(
        self,
        *,
        accepted: int,
        rejected: list[dict[str, Any]],
        retryable: list[dict[str, Any]],
        fully_accounted: bool,
    ) -> None:
        self.accepted = accepted
        self.rejected = rejected
        self.retryable = retryable
        self.fully_accounted = fully_accounted


def _safe_filename(value: str) -> str:
    safe = _SAFE_FILENAME_CHARS.sub("_", value).strip("._")
    return safe or "unknown-session"


class _CircuitBreaker:
    """Trips after consecutive delivery failures to stop hammering a down server.

    States: closed (deliver normally), open (skip the POST and spool directly for
    reset_seconds so a down or rate-limiting server is not hammered), half-open
    (after the cooldown, allow a single probe delivery). A success closes it; a
    failed probe reopens it. Thread-safe. clock is injectable for tests.
    """

    def __init__(
        self,
        failure_threshold: int,
        reset_seconds: float,
        clock: Any = time.monotonic,
    ) -> None:
        self._threshold = max(1, int(failure_threshold))
        self._reset = float(reset_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open = False

    def allow(self) -> bool:
        """True if a delivery may be attempted (closed or half-open probe)."""
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at >= self._reset:
                self._half_open = True
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._half_open:
                self._opened_at = self._clock()  # probe failed; reopen
                self._half_open = False
            elif self._failures >= self._threshold and self._opened_at is None:
                self._opened_at = self._clock()

    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if self._clock() - self._opened_at >= self._reset:
                return "half_open"
            return "open"


def _parse_http_status(exc: Exception) -> int | None:
    """Best-effort extraction of an HTTP status code from a poster error.

    HTTPTransport._post re-raises urllib.error.HTTPError as
    RuntimeError("Promptetheus HTTP <code>: ..."). We parse that prefix so we
    can classify transient vs permanent failures without touching http.py.
    """

    if isinstance(exc, RuntimeError):
        match = re.match(r"Promptetheus HTTP (\d{3})", str(exc))
        if match:
            return int(match.group(1))
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    return None


class DurableHTTPTransport(BaseTransport):
    """Reliable, non-blocking HTTP transport for the FastAPI ingestion contract.

    Events are enqueued and returned from immediately; a single daemon flusher
    thread batches and POSTs them with retry/backoff, spooling and replaying as
    needed. Exposes .endpoint and .api_key for back-compat with
    HTTPTransport.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        *,
        spool_dir: str | Path = ".promptetheus/spool",
        batch_size: int = 50,
        flush_interval: float = 1.0,
        max_retries: int = 5,
        timeout: float | None = None,
        queue_maxsize: int = 10_000,
        max_spool_bytes: int = 256 * 1024 * 1024,
        compress_min_bytes: int = _DEFAULT_COMPRESS_MIN_BYTES,
        circuit_failure_threshold: int = 5,
        circuit_reset_seconds: float = 30.0,
    ) -> None:
        super().__init__()
        self._poster = HTTPTransport(endpoint, api_key=api_key, timeout=timeout)
        # Back-compat surface mirrors HTTPTransport's normalization.
        self.endpoint = self._poster.endpoint
        self.api_key = self._poster.api_key

        # Request bodies whose UTF-8 JSON length is >= this threshold are
        # gzip-compressed with Content-Encoding: gzip; smaller bodies go out
        # uncompressed. 0 disables compression entirely. This is opt-in tuning;
        # the default keeps small bodies (the common case) untouched.
        self.compress_min_bytes = max(0, int(compress_min_bytes))

        self.spool_dir = Path(spool_dir)
        self.batch_size = max(1, int(batch_size))
        self.flush_interval = float(flush_interval)
        self.max_retries = max(0, int(max_retries))
        self.timeout = self._poster.timeout
        # Bounded in-memory queue: on overflow we spill to the spool rather than
        # blocking the caller or growing process memory without bound.
        self.queue_maxsize = max(1, int(queue_maxsize))
        # Configurable on-disk spool cap. When exceeded, the oldest fully
        # delivered (non dead-letter) spool files are pruned first.
        self.max_spool_bytes = max(0, int(max_spool_bytes))

        self._queue: queue.Queue[Any] = queue.Queue(maxsize=self.queue_maxsize)
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._stop = threading.Event()
        # Flush handshake: each flush() bumps the generation under the lock and
        # enqueues a sentinel carrying it; the flusher records the highest
        # generation it has fully drained so flush() can wait for its own drain
        # instead of a shared idle flag the flusher may set for other reasons.
        self._flush_lock = threading.Lock()
        self._flush_cond = threading.Condition(self._flush_lock)
        self._flush_generation = 0
        self._flush_done_generation = 0
        # Latch so the bounded-queue overflow warning is loud but not spammy.
        self._overflow_logged = False
        self._replayed_spool = False
        self._atexit_registered = False
        self._last_spool_replay_failure_at: float | None = None

        # Circuit breaker: stop hammering a down/rate-limiting server.
        self._breaker = _CircuitBreaker(
            circuit_failure_threshold, circuit_reset_seconds
        )
        # Self-observability counters (see stats()).
        self._metrics_lock = threading.Lock()
        self._metrics: dict[str, int] = {
            "enqueued": 0,
            "overflow_spilled": 0,
            "delivered_batches": 0,
            "delivered_events": 0,
            "retries": 0,
            "spooled_events": 0,
            "dead_lettered_events": 0,
            "safe_dropped_events": 0,
            "circuit_skipped_batches": 0,
        }

    def _incr(self, name: str, n: int = 1) -> None:
        with self._metrics_lock:
            self._metrics[name] = self._metrics.get(name, 0) + n

    def stats(self) -> dict[str, Any]:
        """Snapshot of delivery counters, queue depth, and circuit state.

        Self-observability for the durable transport: how many events were
        enqueued, delivered, retried, spooled, or dead-lettered, the current
        in-memory queue depth, and the circuit breaker state (closed/open/
        half_open). Cheap and thread-safe; safe to poll.
        """

        with self._metrics_lock:
            snapshot: dict[str, Any] = dict(self._metrics)
        snapshot["queue_depth"] = self._queue.qsize()
        snapshot["circuit_state"] = self._breaker.state()
        return snapshot

    # -- public API ---------------------------------------------------------

    def create_trace(self, metadata: Mapping[str, Any]) -> None:
        """Create the trace session (POST /api/traces) via the poster.

        Called synchronously by Session.__enter__. Never raises into the
        caller; failures are logged and swallowed (the trace is recreated
        implicitly by the first event batch on the server side anyway).
        """

        try:
            self._poster.create_trace(metadata)
        except Exception:
            logger.exception("Promptetheus durable transport failed to create trace")

    def upload_artifact(
        self,
        session_id: str,
        *,
        body: bytes,
        content_type: str,
        filename: str | None = None,
        artifact_type: str | None = None,
    ) -> dict[str, Any]:
        """Upload artifact metadata through FastAPI (State-0: no raw bytes on wire)."""

        try:
            return self._poster.upload_artifact(
                session_id,
                body=body,
                content_type=content_type,
                filename=filename,
                artifact_type=artifact_type,
            )
        except Exception:
            logger.exception("Promptetheus durable transport failed to upload artifact")
            return {"artifact_id": "", "storage_path": ""}

    def send_event(self, event: Event) -> None:
        """Enqueue one already-enveloped event (non-blocking)."""

        self.send_batch([event])

    def send_batch(self, events: Iterable[Event]) -> None:
        """Enqueue already-enveloped events (non-blocking, never raises)."""

        try:
            if self._closed:
                # Never raise into the caller; a closed transport drops loudly.
                logger.warning(
                    "Promptetheus durable transport is closed; dropping events"
                )
                return
            materialized = [dict(event) for event in events]
            if not materialized:
                return
            self._ensure_thread()
            overflow: list[dict[str, Any]] = []
            for event in materialized:
                try:
                    self._queue.put_nowait(event)
                    self._incr("enqueued")
                except queue.Full:
                    # Bounded queue is saturated (flusher draining slower than
                    # we emit). Spill the overflow to the spool instead of
                    # blocking the caller or dropping silently.
                    overflow.append(event)
            if overflow:
                self._incr("overflow_spilled", len(overflow))
                self._spill_overflow(overflow)
        except Exception:
            logger.exception("Promptetheus durable transport failed to enqueue events")

    def _spill_overflow(self, events: list[dict[str, Any]]) -> None:
        """Spill queue-overflow events to the spool, logging loudly once."""

        if not self._overflow_logged:
            logger.warning(
                "Promptetheus in-memory queue full (maxsize=%d); spilling overflow "
                "events to the spool for replay",
                self.queue_maxsize,
            )
            self._overflow_logged = True
        for session_id, session_events in self._group_by_session(events).items():
            self._spool(session_id, session_events)

    def flush(self, timeout: float | None = None) -> None:
        """Drain the queue, attempt spool replay, and block for in-flight work.

        Blocks up to timeout seconds (None waits indefinitely) for the
        flusher to finish. Never raises into the caller.
        """

        try:
            deadline = None if timeout is None else time.monotonic() + timeout

            if self._thread is not None and self._thread.is_alive():
                # Wake the flusher and wait for it to fully drain everything
                # enqueued up to and including our sentinel. The generation token
                # ties the wait to this specific drain request, so the flusher
                # cannot satisfy us early for an unrelated empty-queue moment.
                with self._flush_lock:
                    self._flush_generation += 1
                    generation = self._flush_generation
                if self._enqueue_flush_sentinel(generation, deadline):
                    self._wait_flush(generation, deadline)
            else:
                # No flusher running: drain synchronously on the caller thread.
                self._drain_queue_sync()

            remaining = (
                None if deadline is None else max(0.0, deadline - time.monotonic())
            )
            self._replay_spool(remaining)
        except Exception:
            logger.exception("Promptetheus durable transport failed during flush")

    def close(self) -> None:
        """Flush, then stop the flusher thread. Thread-safe; never deadlocks."""

        if self._closed:
            return
        try:
            self.flush(timeout=self.timeout)
        finally:
            self._stop.set()
            thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                # Wake the flusher so it observes the stop signal promptly.
                try:
                    self._queue.put_nowait(_FlushSentinel(0))
                except queue.Full:
                    pass
                thread.join(timeout=max(self.timeout, 1.0))
            self._closed = True

    def __enter__(self) -> "DurableHTTPTransport":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    # -- flusher thread -----------------------------------------------------

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if not self._atexit_registered:
                atexit.register(self._atexit_flush)
                self._atexit_registered = True
            self._stop.clear()
            thread = threading.Thread(
                target=self._run,
                name="promptetheus-durable-flusher",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def _run(self) -> None:
        # Replay anything left over from a previous process on startup.
        self._replay_spool(None)
        while not self._stop.is_set():
            batch, sentinel_gen = self._collect_batch()
            if batch:
                self._deliver_with_retry(batch)
            if self._queue.empty():
                self._replay_spool(None)
            # A sentinel is satisfied only once the queue is drained AND its
            # preceding events have been delivered, so signal completion here.
            if sentinel_gen:
                self._signal_flush_done(sentinel_gen)
        # Drain anything left after a stop signal so close() loses nothing.
        while True:
            leftover, sentinel_gen = self._collect_batch(block=False)
            if leftover:
                self._deliver_with_retry(leftover)
            if sentinel_gen:
                self._signal_flush_done(sentinel_gen)
            if not leftover:
                break
        # Unblock any flush() still waiting; the queue is fully drained.
        self._signal_flush_done(self._flush_generation)

    def _collect_batch(self, block: bool = True) -> tuple[list[dict[str, Any]], int]:
        """Drain up to batch_size events from the queue.

        When block is True the first item is awaited up to flush_interval
        so the thread parks while idle instead of spinning. Returns the collected
        events plus the highest flush-sentinel generation seen in this drain (0
        if none), so the caller can signal flush completion only after the
        batch's events have actually been delivered.
        """

        batch: list[dict[str, Any]] = []
        sentinel_gen = 0
        try:
            if block:
                try:
                    first = self._queue.get(timeout=self.flush_interval)
                except queue.Empty:
                    return batch, sentinel_gen
                if isinstance(first, _FlushSentinel):
                    sentinel_gen = max(sentinel_gen, first.generation)
                else:
                    batch.append(first)
        except Exception:
            logger.exception("Promptetheus durable transport failed to read queue")
            return batch, sentinel_gen

        while len(batch) < self.batch_size:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, _FlushSentinel):
                sentinel_gen = max(sentinel_gen, item.generation)
                continue
            batch.append(item)
        return batch, sentinel_gen

    def _drain_queue_sync(self) -> None:
        """Drain and deliver the queue on the calling thread (no flusher)."""

        while True:
            batch, _ = self._collect_batch(block=False)
            if not batch:
                break
            self._deliver_with_retry(batch)

    def _signal_flush_done(self, generation: int) -> None:
        """Record that all work up through generation is drained."""

        if generation <= 0:
            return
        with self._flush_cond:
            if generation > self._flush_done_generation:
                self._flush_done_generation = generation
            self._flush_cond.notify_all()

    def _wait_flush(self, generation: int, deadline: float | None) -> None:
        """Block until the flusher reports it drained generation (or timeout)."""

        with self._flush_cond:
            while self._flush_done_generation < generation:
                if self._thread is None or not self._thread.is_alive():
                    return
                if deadline is None:
                    self._flush_cond.wait(timeout=0.1)
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return
                    self._flush_cond.wait(timeout=min(0.1, remaining))

    def _enqueue_flush_sentinel(
        self, generation: int, deadline: float | None
    ) -> bool:
        """Wake the flusher without blocking past flush(timeout=...)."""

        sentinel = _FlushSentinel(generation)
        while True:
            try:
                self._queue.put_nowait(sentinel)
                return True
            except queue.Full:
                if self._thread is None or not self._thread.is_alive():
                    return False
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        logger.warning(
                            "Promptetheus flush timed out before the flusher "
                            "could be signaled; queue_depth=%d",
                            self._queue.qsize(),
                        )
                        return False
                    time.sleep(min(0.01, remaining))
                else:
                    time.sleep(0.01)

    # -- delivery -----------------------------------------------------------

    def _deliver_with_retry(self, batch: list[dict[str, Any]]) -> None:
        """Deliver a batch grouped by session; spool on exhaustion."""

        for session_id, events in self._group_by_session(batch).items():
            self._post_session_events(session_id, events)

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """POST a JSON payload, gzip-compressing the body past the threshold.

        Mirrors HTTPTransport._post (same URL joining, auth header, and HTTP
        error -> RuntimeError("Promptetheus HTTP <code>: ...") translation that
        _parse_http_status depends on) but adds opt-in gzip: when the encoded
        body is at least compress_min_bytes we gzip it and set
        Content-Encoding: gzip. Small bodies are sent uncompressed exactly as
        before, so the on-the-wire format for tiny payloads is unchanged.

        Compression lives here rather than in the low-level HTTPTransport so the
        synchronous poster keeps its minimal, dependency-light surface and the
        durable layer owns the wire-size optimization.
        """

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.compress_min_bytes and len(body) >= self.compress_min_bytes:
            # mtime=0 keeps the gzip output deterministic (no embedded timestamp)
            # so identical payloads compress to identical bytes.
            body = gzip.compress(body, mtime=0)
            headers["Content-Encoding"] = "gzip"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            urljoin(self.endpoint, path.lstrip("/")),
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            # Reference urlopen through the http module so tests that patch
            # promptetheus.transport.http.urlopen intercept durable POSTs too,
            # exactly as they did when delivery delegated to HTTPTransport._post.
            with _http.urlopen(request, timeout=self.timeout) as response:
                response_body = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Promptetheus HTTP {exc.code}: {detail}") from exc
        if not response_body:
            return {}
        return json.loads(response_body.decode("utf-8"))

    def _post_session_events(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> None:
        path = f"/api/traces/{session_id}/events"
        # Circuit open: skip the attempt and spool directly so a down or
        # rate-limiting server is not hammered. Replay drains the spool later.
        if not self._breaker.allow():
            logger.warning(
                "Promptetheus circuit open; spooling %s without attempting", session_id
            )
            self._incr("circuit_skipped_batches")
            self._spool(session_id, events)
            return
        attempt = 0
        while True:
            try:
                response = self._post(path, {"events": events})
            except URLError as exc:
                # Network-level failure: always transient.
                if attempt >= self.max_retries:
                    logger.warning(
                        "Promptetheus delivery exhausted retries (network) for %s: %s; spooling",
                        session_id,
                        exc,
                    )
                    self._breaker.record_failure()
                    self._spool(session_id, events)
                    return
                self._incr("retries")
                self._sleep_backoff(attempt)
                attempt += 1
                continue
            except Exception as exc:
                status = _parse_http_status(exc)
                if status in _PERMANENT_STATUS:
                    logger.warning(
                        "Promptetheus permanent rejection (HTTP %s) for %s; dead-lettering batch",
                        status,
                        session_id,
                    )
                    self._breaker.record_success()  # server answered; transport is healthy
                    self._dead_letter(session_id, events, reason=f"http_{status}")
                    return
                if status is None or status == 429 or status >= 500:
                    # Transient: 5xx / 429 / unclassified.
                    if attempt >= self.max_retries:
                        logger.warning(
                            "Promptetheus delivery exhausted retries (HTTP %s) for %s; spooling",
                            status,
                            session_id,
                        )
                        self._breaker.record_failure()
                        self._spool(session_id, events)
                        return
                    self._incr("retries")
                    self._sleep_backoff(attempt)
                    attempt += 1
                    continue
                # Other non-retryable 4xx. A narrow allowlist (e.g. 409
                # duplicate) is genuinely safe to drop; anything else (405, 411,
                # 413, ...) is dead-lettered so the events leave a forensic
                # record instead of vanishing silently.
                if status in _SAFE_DROP_STATUS:
                    logger.warning(
                        "Promptetheus safe-to-drop response (HTTP %s) for %s; dropping batch",
                        status,
                        session_id,
                    )
                    self._breaker.record_success()  # server answered; not a transport fault
                    self._incr("safe_dropped_events", len(events))
                    return
                logger.warning(
                    "Promptetheus non-retryable response (HTTP %s) for %s; dead-lettering batch",
                    status,
                    session_id,
                )
                self._breaker.record_success()  # server answered; transport is healthy
                self._dead_letter(session_id, events, reason=f"http_{status}")
                return
            else:
                self._breaker.record_success()
                outcome = self._resolve_accept_reject(session_id, events, response)
                if outcome.rejected:
                    self._write_dead_letter(session_id, outcome.rejected)
                if outcome.fully_accounted:
                    self._incr("delivered_batches")
                    self._incr("delivered_events", outcome.accepted)
                else:
                    logger.warning(
                        "Promptetheus ambiguous 2xx response for %s; spooling "
                        "%d unaccounted event(s) for retry",
                        session_id,
                        len(outcome.retryable),
                    )
                    if outcome.retryable:
                        self._spool(session_id, outcome.retryable)
                return

    def _resolve_accept_reject(
        self,
        session_id: str,
        events: list[dict[str, Any]],
        response: Mapping[str, Any] | None,
    ) -> _AcceptRejectOutcome:
        """Classify a batch response into accepted, rejected, and retryable events."""

        accepted: int | None = None
        rejected_raw: list[Any] = []
        if isinstance(response, Mapping):
            accepted_raw = response.get("accepted")
            if (
                isinstance(accepted_raw, int)
                and not isinstance(accepted_raw, bool)
                and accepted_raw >= 0
            ):
                accepted = accepted_raw
            rejected_value = response.get("rejected")
            if isinstance(rejected_value, list):
                rejected_raw = rejected_value

        by_key = {
            str(event.get("idempotency_key")): index
            for index, event in enumerate(events)
        }
        rejected_indexes: set[int] = set()
        rejected_events: list[dict[str, Any]] = []
        for entry in rejected_raw:
            if not isinstance(entry, Mapping):
                continue
            key = entry.get("idempotency_key")
            reason = entry.get("reason", "rejected")
            index = entry.get("index")
            event_index = by_key.get(str(key))
            if event_index is None and isinstance(index, int) and 0 <= index < len(events):
                event_index = index
            if event_index is None:
                logger.warning(
                    "Promptetheus rejected event not found in batch for %s (key=%r index=%r)",
                    session_id,
                    key,
                    index,
                )
                continue
            if event_index in rejected_indexes:
                continue
            rejected_indexes.add(event_index)
            record = dict(events[event_index])
            record["_reject_reason"] = reason
            rejected_events.append(record)

        if rejected_events:
            logger.warning(
                "Promptetheus dead-lettering %d rejected event(s) for %s",
                len(rejected_events),
                session_id,
            )

        non_rejected = [
            event for index, event in enumerate(events) if index not in rejected_indexes
        ]
        rejected_count = len(rejected_indexes)
        fully_accounted = accepted is not None and accepted + rejected_count == len(events)
        if fully_accounted:
            accepted_count = accepted
            if accepted_count is None:
                accepted_count = 0
            return _AcceptRejectOutcome(
                accepted=accepted_count,
                rejected=rejected_events,
                retryable=[],
                fully_accounted=True,
            )

        if accepted is None:
            logger.warning(
                "Promptetheus event POST response for %s is missing valid accepted count",
                session_id,
            )
        else:
            logger.warning(
                "Promptetheus event POST response for %s accounted for %d/%d event(s)",
                session_id,
                accepted + rejected_count,
                len(events),
            )
        return _AcceptRejectOutcome(
            accepted=max(accepted or 0, 0),
            rejected=rejected_events,
            retryable=non_rejected,
            fully_accounted=False,
        )

    def _backoff_delay(self, attempt: int) -> float:
        """Full-jitter exponential backoff delay in seconds for a retry attempt.

        The backoff window grows as _BACKOFF_BASE * 2**attempt, capped at
        _BACKOFF_CAP, and the actual delay is drawn uniformly from [0, window)
        using random.uniform. Full jitter spreads concurrent retriers out across
        the window so they do not wake in lockstep and stampede a recovering
        server. Split out from _sleep_backoff so the jitter is unit-testable
        without sleeping.
        """

        window = min(_BACKOFF_BASE * (2**attempt), _BACKOFF_CAP)
        return random.uniform(0.0, window)

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self._backoff_delay(attempt)
        # Wait on the stop event so shutdown interrupts long backoffs.
        if self._stop.wait(timeout=delay):
            return

    # -- spool / dead-letter ------------------------------------------------

    def _spool_path(self, session_id: str) -> Path:
        return self.spool_dir / f"{_safe_filename(session_id)}.jsonl"

    @staticmethod
    def _is_claimed_spool_path(path: Path) -> bool:
        return _REPLAYING_MARKER in path.stem

    def _claim_spool_file(self, path: Path) -> Path | None:
        """Atomically move a live spool file out of _spool()'s append path."""

        if self._is_claimed_spool_path(path):
            return path
        claimed = path.with_name(
            f"{path.stem}{_REPLAYING_MARKER}{os.getpid()}-"
            f"{threading.get_ident()}-{time.monotonic_ns()}{path.suffix}"
        )
        try:
            path.rename(claimed)
            return claimed
        except FileNotFoundError:
            return None
        except Exception:
            logger.exception("Promptetheus failed to claim spool file %s", path)
            return None

    @staticmethod
    def _session_from_spool_path(path: Path) -> str:
        stem = path.stem
        marker_index = stem.find(_REPLAYING_MARKER)
        if marker_index >= 0:
            stem = stem[:marker_index]
        return stem or "unknown-session"

    def _dead_letter_dir(self) -> Path:
        return self.spool_dir / _DEAD_LETTER_DIR

    def _dead_letter_path(self, session_id: str) -> Path:
        return self._dead_letter_dir() / f"{_safe_filename(session_id)}.jsonl"

    def _spool(self, session_id: str, events: list[dict[str, Any]]) -> None:
        try:
            self.spool_dir.mkdir(parents=True, exist_ok=True)
            with self._spool_path(session_id).open("a", encoding="utf-8") as file:
                for event in events:
                    file.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
                    file.write("\n")
        except Exception:
            logger.exception("Promptetheus failed to spool events for %s", session_id)
        else:
            self._incr("spooled_events", len(events))
            self._prune_spool()

    def _prune_spool(self) -> None:
        """Enforce the configurable spool size cap.

        When the spool directory exceeds max_spool_bytes we delete the
        oldest replayable (non dead-letter) spool files first, logging loudly,
        and keep dead-letter files so forensic records survive. A cap of 0 means
        unbounded (pruning disabled).
        """

        if self.max_spool_bytes <= 0:
            return
        try:
            if not self.spool_dir.exists():
                return
            files: list[tuple[float, int, Path]] = []
            dead_letter_bytes = 0
            dead_letter_dir = self._dead_letter_dir()
            if dead_letter_dir.exists():
                for path in dead_letter_dir.glob("*.jsonl"):
                    try:
                        dead_letter_bytes += path.stat().st_size
                    except OSError:
                        continue
            for path in self.spool_dir.glob("*.jsonl"):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files.append((stat.st_mtime, stat.st_size, path))

            total = dead_letter_bytes + sum(size for _, size, _ in files)
            if total <= self.max_spool_bytes:
                return

            # Oldest replayable files pruned first (mtime ascending).
            files.sort(key=lambda item: item[0])
            pruned = 0
            for _mtime, size, path in files:
                if total <= self.max_spool_bytes:
                    break
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    logger.exception("Promptetheus failed to prune spool file %s", path)
                    continue
                total -= size
                pruned += 1
            if pruned:
                logger.warning(
                    "Promptetheus spool exceeded cap (%d bytes); pruned %d oldest "
                    "spool file(s) to reclaim space",
                    self.max_spool_bytes,
                    pruned,
                )
        except Exception:
            logger.exception("Promptetheus failed to prune spool directory")

    def _dead_letter(
        self, session_id: str, events: list[dict[str, Any]], *, reason: str
    ) -> None:
        records = []
        for event in events:
            record = dict(event)
            record["_reject_reason"] = reason
            records.append(record)
        self._write_dead_letter(session_id, records)

    def _write_dead_letter(
        self, session_id: str, records: list[dict[str, Any]]
    ) -> None:
        try:
            dead_letter_dir = self._dead_letter_dir()
            dead_letter_dir.mkdir(parents=True, exist_ok=True)
            with self._dead_letter_path(session_id).open("a", encoding="utf-8") as file:
                for record in records:
                    file.write(
                        json.dumps(record, sort_keys=True, separators=(",", ":"))
                    )
                    file.write("\n")
        except Exception:
            logger.exception(
                "Promptetheus failed to write dead-letter for %s", session_id
            )
        else:
            self._incr("dead_lettered_events", len(records))

    def _replay_spool(self, timeout: float | None) -> None:
        """Re-POST spooled batches through FastAPI; delete files once accepted.

        Replays are safe because the server dedupes on idempotency_key. A
        spool file is removed only after every event in it is accepted (not
        rejected and not failed).
        """

        deadline = None if timeout is None else time.monotonic() + timeout
        if timeout is None and self._spool_replay_in_cooldown():
            return
        try:
            if not self.spool_dir.exists():
                self._replayed_spool = True
                return
            spool_files = sorted(self.spool_dir.glob("*.jsonl"))
        except Exception:
            logger.exception("Promptetheus failed to list spool directory")
            return

        for path in spool_files:
            if deadline is not None and time.monotonic() >= deadline:
                return
            self._replay_spool_file(path)
        self._replayed_spool = True

    def _replay_spool_file(self, path: Path) -> None:
        claimed_path = self._claim_spool_file(path)
        if claimed_path is None:
            return
        try:
            session_id = self._session_from_spool_path(claimed_path)
            events: list[dict[str, Any]] = []
            for line in claimed_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(
                        "Promptetheus skipping malformed spool line in %s",
                        claimed_path.name,
                    )
            if not events:
                claimed_path.unlink(missing_ok=True)
                return
            # Prefer the events' own session_id (the spool filename is a
            # sanitized, possibly lossy derivation of it).
            real_id = events[0].get("session_id")
            if isinstance(real_id, str) and real_id:
                session_id = real_id
        except FileNotFoundError:
            return
        except Exception:
            logger.exception("Promptetheus failed to read spool file %s", claimed_path)
            return

        try:
            response = self._post(
                f"/api/traces/{session_id}/events", {"events": events}
            )
        except URLError:
            # Still offline; leave the spool file for the next attempt.
            self._mark_spool_replay_failure()
            return
        except Exception as exc:
            status = _parse_http_status(exc)
            if status in _PERMANENT_STATUS:
                logger.warning(
                    "Promptetheus permanent rejection replaying spool for %s (HTTP %s); dead-lettering",
                    session_id,
                    status,
                )
                self._dead_letter(session_id, events, reason=f"http_{status}")
                self._safe_unlink(claimed_path)
            else:
                logger.warning(
                    "Promptetheus transient failure replaying spool for %s (HTTP %s); keeping file",
                    session_id,
                    status,
                )
                self._mark_spool_replay_failure()
            return

        outcome = self._resolve_accept_reject(session_id, events, response)
        self._last_spool_replay_failure_at = None
        if outcome.rejected:
            self._write_dead_letter(session_id, outcome.rejected)
        if outcome.fully_accounted:
            # Accepted (possibly with per-event rejections we dead-letter): the
            # claimed spool file is fully resolved, so remove only that file.
            self._safe_unlink(claimed_path)
            return

        logger.warning(
            "Promptetheus ambiguous 2xx response replaying spool for %s; keeping "
            "%d unaccounted event(s) for retry",
            session_id,
            len(outcome.retryable),
        )
        if outcome.retryable:
            self._rewrite_spool_file(claimed_path, outcome.retryable)
        else:
            self._safe_unlink(claimed_path)

    def _spool_replay_in_cooldown(self) -> bool:
        if self._last_spool_replay_failure_at is None:
            return False
        return (
            time.monotonic() - self._last_spool_replay_failure_at
            < _SPOOL_REPLAY_FAILURE_COOLDOWN
        )

    def _mark_spool_replay_failure(self) -> None:
        if self._last_spool_replay_failure_at is None:
            logger.warning(
                "Promptetheus pausing spool replay for %.0fs after transient failure",
                _SPOOL_REPLAY_FAILURE_COOLDOWN,
            )
        self._last_spool_replay_failure_at = time.monotonic()

    @staticmethod
    def _rewrite_spool_file(path: Path, events: list[dict[str, Any]]) -> None:
        try:
            with path.open("w", encoding="utf-8") as file:
                for event in events:
                    file.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
                    file.write("\n")
        except Exception:
            logger.exception("Promptetheus failed to rewrite spool file %s", path)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.exception("Promptetheus failed to delete spool file %s", path)

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _group_by_session(
        events: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            session_id = str(event.get("session_id") or "unknown-session")
            grouped.setdefault(session_id, []).append(event)
        return grouped

    def _atexit_flush(self) -> None:
        try:
            self.close()
        except Exception:
            logger.exception(
                "Promptetheus durable transport failed during atexit flush"
            )
