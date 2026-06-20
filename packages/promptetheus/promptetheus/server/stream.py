"""In-process Server-Sent-Events pub/sub hub for the State-0 spine.

StreamHub is a tiny single-instance async fan-out: ingestion publishes each
accepted event with its owning workspace_id, and every GET /api/stream
subscriber receives the events that match its workspace + optional project/session
filters. There is no cross-process broker in State 0 (the hub lives on
app.state); a hosted build swaps this for a real pub/sub without changing the
route.

Each delivered SSE record is a fully-formed text/event-stream block string
(event:/data: lines terminated by a blank line), so the route can stream
the hub's output verbatim. Heartbeats are emitted as SSE comment lines.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

__all__ = ["StreamHub", "format_sse", "format_heartbeat"]

#: Seconds between heartbeats when no live event arrives. Keeps proxies from
#: closing an idle SSE connection.
DEFAULT_HEARTBEAT_SECONDS = 15.0


def format_sse(event: dict[str, Any], *, event_name: str = "event") -> str:
    """Render one event dict as a text/event-stream record block."""

    data = json.dumps(event, default=str)
    return f"event: {event_name}\ndata: {data}\n\n"


def format_heartbeat() -> str:
    """Render an SSE heartbeat (a comment line, ignored by EventSource clients)."""

    return ": heartbeat\n\n"


def _matches(
    event: dict[str, Any],
    *,
    project_id: str | None,
    session_id: str | None,
) -> bool:
    """True when event passes the subscriber's project/session filters."""

    if session_id is not None and str(event.get("session_id")) != session_id:
        return False
    if project_id is not None and str(event.get("project_id")) != project_id:
        return False
    return True


class _Subscription:
    """A single live subscriber's queue + its workspace/project/session filters."""

    __slots__ = ("workspace_id", "project_id", "session_id", "queue")

    def __init__(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        session_id: str | None,
    ) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.session_id = session_id
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def wants(self, workspace_id: str, event: dict[str, Any]) -> bool:
        if workspace_id != self.workspace_id:
            return False
        return _matches(event, project_id=self.project_id, session_id=self.session_id)


class StreamHub:
    """In-process async pub/sub keyed by workspace_id.

    publish is synchronous and never blocks (it enqueues into each matching
    subscriber's unbounded queue). subscribe is an async generator that yields
    formatted SSE record strings for matching live events, interleaved with
    heartbeats; backfill of stored events is handled by the route before it begins
    iterating the live stream.
    """

    def __init__(self, *, heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS) -> None:
        self._heartbeat_seconds = heartbeat_seconds
        self._subscribers: set[_Subscription] = set()

    def publish(self, workspace_id: str, event: dict[str, Any]) -> None:
        """Fan event out to every subscriber whose filters match."""

        for sub in list(self._subscribers):
            if sub.wants(workspace_id, event):
                sub.queue.put_nowait(dict(event))

    async def subscribe(
        self,
        workspace_id: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield formatted SSE records for matching live events, with heartbeats.

        The generator registers a subscription on entry and removes it on exit
        (including cancellation / client disconnect). When no event arrives within
        heartbeat_seconds a heartbeat comment is yielded instead.
        """

        sub = _Subscription(
            workspace_id=workspace_id,
            project_id=project_id,
            session_id=session_id,
        )
        self._subscribers.add(sub)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        sub.queue.get(), timeout=self._heartbeat_seconds
                    )
                except asyncio.TimeoutError:
                    yield format_heartbeat()
                    continue
                yield format_sse(event)
        finally:
            self._subscribers.discard(sub)

    @property
    def subscriber_count(self) -> int:
        """Number of currently-registered subscribers (for tests/observability)."""

        return len(self._subscribers)
