"""Async-native session for Promptetheus instrumentation.

AsyncSession mirrors the synchronous Session as an async context manager. It is
opt-in and changes nothing about the sync path: existing code keeps using
Session unchanged.

The async value-add is the lifecycle, not the event helpers. Stamping the
envelope (seq, idempotency_key, timestamp), validating, redacting, and the
span / run-tree model are all loop-agnostic and non-blocking, so AsyncSession
inherits them from Session verbatim rather than duplicating them. What it adds:

- async with support (__aenter__ / __aexit__) so a session opens and closes
  inside an event loop, with the same guarantee as Session that __aexit__ emits
  a terminal session_end (completed or failed) even when the body raises.
- an awaitable flush. When the configured transport already exposes an awaitable
  flush (for example AsyncHTTPTransport), AsyncSession awaits it directly. When
  the transport's flush is the ordinary synchronous, non-blocking kind (for
  example DurableHTTPTransport, whose send and flush already hand work to a
  background thread), AsyncSession runs that flush in a thread executor so it
  never blocks the event loop.
- aspan: an async context manager mirroring Session.span for use with
  async with. It shares Session's span-stack machinery, so spans opened with
  aspan and span nest together and stamp span_id / parent_id identically.

The event helpers (user_message, tool_call, span, goal_check, ...) are inherited
unchanged. They are synchronous and non-blocking by contract, so calling them
from async code is correct and does not need awaiting.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, AsyncIterator, Mapping

from .session import Session, _current_session, logger


class AsyncSession(Session):
    """A single observed agent run, driven from async code.

    Use it as an async context manager:

        async with AsyncSession(agent="a", user_goal="g", transport=t) as session:
            session.user_message("hi")
            async with session.aspan("step"):
                session.tool_call("search")
            await session.flush()

    All of Session's typed event helpers and the synchronous span context
    manager are available unchanged; only the lifecycle and flush are async.
    """

    async def __aenter__(self) -> "AsyncSession":
        # Mirror Session.__enter__ exactly: set the current-session ContextVar,
        # create the trace eagerly in immediate (non tail-sample) mode, and emit
        # the session_started state_change. Reusing the sync helpers keeps the
        # envelope and trace-create behavior identical across sync and async.
        self._ctx_token = _current_session.set(self)
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

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if not self._ended:
            if exc is None:
                self.end("completed")
            else:
                self.end(
                    "failed",
                    error=f"{exc_type.__name__ if exc_type else 'Error'}: {exc}",
                )
        await self.flush()
        if self._ctx_token is not None:
            _current_session.reset(self._ctx_token)
            self._ctx_token = None
        return False

    @asynccontextmanager
    async def aspan(
        self, name: str, metadata: Mapping[str, Any] | None = None
    ) -> AsyncIterator[str]:
        """Open a run-tree span around an async block.

        Async mirror of Session.span: mints a span_id, records parent_id from the
        current top-of-stack span, pushes the span, emits span_start, yields the
        span_id, then emits span_end and pops on exit. It shares the exact
        span-stack machinery as span, so spans opened with aspan and span nest
        together and every event inside is stamped with this span_id / parent_id.
        """

        span_id = self._new_async_span_id()
        token = self._push_span(span_id)
        # Mirror Session.span: capture a monotonic start so span_end carries a
        # clock-adjustment-immune duration_ms.
        started_at = time.monotonic()
        try:
            self.event(
                "state_change", {"name": "span_start", "span_name": name}, metadata
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
                self._pop_span(token)

    @staticmethod
    def _new_async_span_id() -> str:
        # Use the same id scheme as the sync span model.
        from .session import _new_span_id

        return _new_span_id()

    def _pop_span(self, token: Any) -> None:
        from .session import _span_stacks

        _span_stacks.reset(token)

    def end(
        self, status: str = "completed", error: str | None = None
    ) -> dict[str, Any]:
        """End the session, emitting session_end and resolving tail sampling.

        Mirrors Session.end but performs a synchronous transport flush instead of
        the awaitable flush this class adds. This is what __aexit__ and the sync
        callers invoke; it must not leave an un-awaited coroutine. Async callers
        that want to await the transport drain should use end_async (or rely on
        __aexit__, which awaits flush after this returns).
        """

        if self._terminal_event is not None:
            return self._terminal_event
        self._ended = True
        event = self.event("session_end", {"status": status, "error": error})
        self._terminal_event = event
        if self.tail_sample:
            self._resolve_tail()
        self._sync_flush()
        return event

    def _sync_flush(self, timeout: float | None = None) -> None:
        """Synchronous best-effort transport flush (never awaits, never raises).

        Used by end(); avoids invoking the awaitable flush override so no
        coroutine is created and discarded. An awaitable transport flush is
        skipped here (it is awaited by __aexit__ / end_async instead).
        """

        transport = self._transport
        if transport is None or not hasattr(transport, "flush"):
            return
        try:
            try:
                result = transport.flush(timeout=timeout)
            except TypeError:
                result = transport.flush()
        except Exception:
            logger.exception("Promptetheus transport failed while flushing")
            return
        if inspect.isawaitable(result):
            # Cannot await from this synchronous path; close it cleanly so no
            # un-awaited-coroutine warning is emitted. __aexit__ / end_async runs
            # the real awaitable flush.
            close = getattr(result, "close", None)
            if callable(close):
                close()

    async def end_async(
        self, status: str = "completed", error: str | None = None
    ) -> dict[str, Any]:
        """End the session and await the flush.

        Convenience for code that ends a session explicitly without async with.
        Session.end already emits session_end, resolves tail sampling, and calls
        the synchronous flush; end_async additionally awaits the async flush so an
        awaitable transport is fully drained. Calling Session.end directly also
        works and stays non-blocking.
        """

        event = self.end(status, error=error)
        await self.flush()
        return event

    async def flush(self, timeout: float | None = None) -> None:  # type: ignore[override]
        """Flush the transport without blocking the event loop.

        If the transport's flush is awaitable (for example AsyncHTTPTransport),
        await it. Otherwise run the synchronous flush in a thread executor so a
        slow or blocking flush cannot stall the loop. Never raises into the
        caller; failures are logged by the transport's own flush.
        """

        transport = self._transport
        if transport is None or not hasattr(transport, "flush"):
            return

        flush = transport.flush
        try:
            if inspect.iscoroutinefunction(flush):
                try:
                    await flush(timeout=timeout)
                except TypeError:
                    await flush()
                return

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._call_sync_flush, flush, timeout
            )
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("Promptetheus transport failed while flushing")

    @staticmethod
    def _call_sync_flush(flush: Any, timeout: float | None) -> Any:
        try:
            return flush(timeout=timeout)
        except TypeError:
            return flush()
        except Exception:
            logger.exception("Promptetheus transport failed while flushing")
        return None

    async def aflush_blocking(self, timeout: float | None = None) -> None:
        """Run a purely synchronous, potentially blocking flush off the loop.

        Provided for transports whose flush blocks the calling thread (rather
        than the non-blocking DurableHTTPTransport). Offloads the flush to the
        default thread executor so the event loop stays responsive.
        """

        transport = self._transport
        if transport is None or not hasattr(transport, "flush"):
            return

        def _run() -> None:
            try:
                transport.flush(timeout=timeout)
            except TypeError:
                try:
                    transport.flush()
                except Exception:
                    return
            except Exception:
                return

        await asyncio.get_running_loop().run_in_executor(None, _run)


__all__ = ["AsyncSession"]
