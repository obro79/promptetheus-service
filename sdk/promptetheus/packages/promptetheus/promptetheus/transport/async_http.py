"""Async-friendly HTTP transport for Promptetheus events.

This is an optional, opt-in async delivery path built on httpx.AsyncClient. It
mirrors the contract the rest of the SDK relies on: send_event / send_batch
queue already-enveloped events, and flush pushes them to FastAPI. The difference
is that the delivery primitives here are awaitable, so an AsyncSession can flush
without blocking its event loop.

Design notes:

- This transport buffers events in memory and posts them on flush (grouped by
  session, preserving (session_id, seq) order). It is intentionally simpler than
  the synchronous DurableHTTPTransport: no background flusher thread, no on-disk
  spool, no retry/backoff. AsyncSession can also be pointed at the existing
  DurableHTTPTransport (whose send is already non-blocking) when those durability
  guarantees are wanted; see session_async for the choice.
- Instrumentation never raises into the host agent. Delivery failures are logged
  via the promptetheus logger and swallowed. Unsent events stay buffered so a
  later flush can retry them.
- httpx is an optional dependency (declared under the dev extra). Importing this
  module without httpx installed raises a clear error only when the transport is
  actually constructed, never at package import time.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

logger = logging.getLogger("promptetheus")

Event = Mapping[str, Any]


def _require_httpx() -> Any:
    try:
        import httpx
    except Exception as exc:  # pragma: no cover - exercised only without httpx
        raise RuntimeError(
            "AsyncHTTPTransport requires httpx. Install it with "
            "pip install 'promptetheus[dev]' or pip install httpx."
        ) from exc
    return httpx


def _normalize_endpoint(endpoint: str) -> str:
    """Strip a trailing slash so path joins are predictable."""

    return endpoint.rstrip("/")


class AsyncHTTPTransport:
    """Awaitable HTTP transport for the FastAPI ingestion contract.

    Events are buffered by send_event / send_batch (both synchronous and
    non-blocking so they compose with Session's event helpers) and posted to
    FastAPI by the awaitable flush. Construct one per event loop and close it
    with aclose (or use it as an async context manager).
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        *,
        timeout: float = 5.0,
        client: Any | None = None,
    ) -> None:
        httpx = _require_httpx()
        self.endpoint = _normalize_endpoint(endpoint)
        self.api_key = api_key
        self.timeout = float(timeout)
        # Allow an injected client for tests (e.g. an ASGITransport-backed
        # AsyncClient); otherwise build one lazily on first flush so constructing
        # the transport outside a running loop is safe.
        self._client: Any | None = client
        self._owns_client = client is None
        self._httpx = httpx
        self._buffer: list[dict[str, Any]] = []
        self._closed = False
        self._closed_with_pending = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending_count(self) -> int:
        return len(self._buffer)

    @property
    def closed_with_pending(self) -> bool:
        return self._closed_with_pending

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def create_trace(self, metadata: Mapping[str, Any]) -> None:
        """Record a trace-create request to be flushed before its events.

        Mirrors DurableHTTPTransport.create_trace in being synchronous and
        non-blocking. We model trace creation as a buffered control record so the
        single async flush can issue it (POST /api/traces) ahead of the trace's
        events; this keeps Session.__enter__ / AsyncSession.__aenter__ from
        having to await anything.
        """

        self._buffer.append({"__control__": "create_trace", "metadata": dict(metadata)})

    def send_event(self, event: Event) -> None:
        """Buffer one already-enveloped event (non-blocking, never raises)."""

        self.send_batch([event])

    def send_batch(self, events: Iterable[Event]) -> None:
        """Buffer already-enveloped events (non-blocking, never raises)."""

        try:
            if self._closed:
                logger.warning(
                    "Promptetheus async transport is closed; dropping events"
                )
                return
            for event in events:
                self._buffer.append(dict(event))
        except Exception:
            logger.exception("Promptetheus async transport failed to buffer events")

    async def flush(self, timeout: float | None = None) -> None:
        """Post all buffered control records and events to FastAPI.

        Awaitable. Never raises into the caller: on failure the un-delivered
        events are kept in the buffer for a later flush, and the error is logged.
        Records are delivered in buffer order, with events grouped by session so
        a single POST carries a contiguous (session_id, seq) run.
        """

        if not self._buffer:
            return
        pending = self._buffer
        self._buffer = []
        try:
            client = self._ensure_client(timeout)
            await self._drain(client, pending, timeout)
        except Exception:
            # Re-buffer anything we pulled so the next flush can retry it.
            self._buffer = pending + self._buffer
            logger.exception("Promptetheus async transport failed during flush")

    async def _drain(
        self, client: Any, pending: list[dict[str, Any]], timeout: float | None
    ) -> None:
        """Deliver pending records in order; re-buffer the tail on first failure.

        Splits the buffer into runs: control records (create_trace) post on their
        own, and contiguous events for one session post as a single batch. If a
        delivery fails we stop and re-buffer the unsent remainder so ordering and
        at-least-once delivery hold across retries.
        """

        index = 0
        total = len(pending)
        while index < total:
            record = pending[index]
            if record.get("__control__") == "create_trace":
                ok = await self._post_create_trace(client, record["metadata"], timeout)
                if not ok:
                    self._buffer = pending[index:] + self._buffer
                    return
                index += 1
                continue

            # Gather a contiguous run of events for the same session.
            session_id = str(record.get("session_id") or "unknown-session")
            run: list[dict[str, Any]] = []
            while index < total:
                nxt = pending[index]
                if nxt.get("__control__") is not None:
                    break
                if str(nxt.get("session_id") or "unknown-session") != session_id:
                    break
                run.append(nxt)
                index += 1
            retryable = await self._post_events(client, session_id, run, timeout)
            if retryable is None:
                # Re-buffer this run plus everything after it.
                self._buffer = run + pending[index:] + self._buffer
                return
            if retryable:
                # Preserve ordering: retry unaccepted events before later records.
                self._buffer = retryable + pending[index:] + self._buffer
                return

    async def _post_create_trace(
        self, client: Any, metadata: Mapping[str, Any], timeout: float | None
    ) -> bool:
        try:
            response = await client.post(
                f"{self.endpoint}/api/traces",
                json=metadata,
                headers=self._headers(),
                timeout=self.timeout if timeout is None else timeout,
            )
            response.raise_for_status()
            return True
        except Exception:
            logger.exception("Promptetheus async transport failed to create trace")
            return False

    async def _post_events(
        self,
        client: Any,
        session_id: str,
        events: list[dict[str, Any]],
        timeout: float | None,
    ) -> list[dict[str, Any]] | None:
        if not events:
            return []
        try:
            response = await client.post(
                f"{self.endpoint}/api/traces/{session_id}/events",
                json={"events": events},
                headers=self._headers(),
                timeout=self.timeout if timeout is None else timeout,
            )
            response.raise_for_status()
            body = response.json() if response.content else {}
            retryable = self._retryable_after_response(session_id, events, body)
            return retryable
        except Exception:
            logger.exception(
                "Promptetheus async transport failed to deliver %d event(s) for %s",
                len(events),
                session_id,
            )
            return None

    def _retryable_after_response(
        self,
        session_id: str,
        events: list[dict[str, Any]],
        response: Any,
    ) -> list[dict[str, Any]]:
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
            index = entry.get("index")
            event_index = by_key.get(str(key))
            if (
                event_index is None
                and isinstance(index, int)
                and 0 <= index < len(events)
            ):
                event_index = index
            if event_index is None:
                logger.warning(
                    "Promptetheus async transport rejected unknown event for %s "
                    "(key=%r index=%r)",
                    session_id,
                    key,
                    index,
                )
                continue
            if event_index in rejected_indexes:
                continue
            rejected_indexes.add(event_index)
            rejected_events.append(events[event_index])

        rejected_count = len(rejected_indexes)
        fully_accounted = accepted is not None and accepted + rejected_count == len(events)
        if fully_accounted:
            if rejected_events:
                logger.warning(
                    "Promptetheus async transport received %d rejected event(s) "
                    "for %s; keeping them buffered because async transport has "
                    "no dead-letter spool",
                    len(rejected_events),
                    session_id,
                )
            return rejected_events

        retryable = [
            event for index, event in enumerate(events) if index not in rejected_indexes
        ]
        if rejected_events:
            logger.warning(
                "Promptetheus async transport received %d rejected event(s) for %s; "
                "keeping them buffered because async transport has no dead-letter spool",
                len(rejected_events),
                session_id,
            )
            retryable = rejected_events + retryable
        if not fully_accounted:
            accounted = (accepted or 0) + rejected_count
            logger.warning(
                "Promptetheus async transport received ambiguous 2xx response for "
                "%s (%d/%d event(s) accounted); keeping unaccepted events buffered",
                session_id,
                accounted,
                len(events),
            )
        return retryable

    def _ensure_client(self, timeout: float | None) -> Any:
        if self._client is None:
            self._client = self._httpx.AsyncClient(
                timeout=self.timeout if timeout is None else timeout
            )
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        """Flush remaining events, then close an owned httpx client."""

        if self._closed:
            return
        try:
            await self.flush()
            if self._buffer:
                self._closed_with_pending = True
                logger.warning(
                    "Promptetheus async transport closed with %d buffered event(s) "
                    "still undelivered",
                    len(self._buffer),
                )
        finally:
            self._closed = True
            if self._owns_client and self._client is not None:
                try:
                    await self._client.aclose()
                except Exception:
                    logger.exception(
                        "Promptetheus async transport failed to close client"
                    )

    async def __aenter__(self) -> "AsyncHTTPTransport":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        await self.aclose()
        return False


__all__ = ["AsyncHTTPTransport"]
