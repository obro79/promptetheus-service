"""Dependency-free transport primitives for Promptetheus SDK events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

Event = Mapping[str, Any]


class Transport(Protocol):
    """Common event transport interface used by SDK sessions."""

    def send_event(self, event: Event) -> None:
        """Queue or deliver one already-enveloped event."""

    def send_batch(self, events: Iterable[Event]) -> None:
        """Queue or deliver multiple already-enveloped events in order."""

    def flush(self, timeout: float | None = None) -> None:
        """Push any buffered events to the transport's durable destination."""

    def close(self) -> None:
        """Flush and release transport resources."""


class BaseTransport:
    """Small base class with practical defaults for simple transports."""

    def __init__(self) -> None:
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def send_event(self, event: Event) -> None:
        raise NotImplementedError

    def send_batch(self, events: Iterable[Event]) -> None:
        self._ensure_open()
        for event in events:
            self.send_event(event)

    def flush(self, timeout: float | None = None) -> None:
        self._ensure_open()

    def close(self) -> None:
        if not self._closed:
            self.flush()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError(f"{self.__class__.__name__} is closed")


class InMemoryTransport(BaseTransport):
    """Transport that records events in memory for tests and local assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []
        self.flush_count = 0

    def send_event(self, event: Event) -> None:
        self._ensure_open()
        self.events.append(dict(event))

    def upload_artifact(
        self,
        session_id: str,
        *,
        body: bytes,
        content_type: str,
        filename: str | None = None,
        artifact_type: str | None = None,
    ) -> dict[str, Any]:
        artifact_id = f"artifact_{len(self.events) + 1}"
        storage_path = (
            f"artifacts/memory/{session_id}/{artifact_id}/{filename or 'artifact.bin'}"
        )
        return {"artifact_id": artifact_id, "storage_path": storage_path}

    def flush(self, timeout: float | None = None) -> None:
        self._ensure_open()
        self.flush_count += 1


# Imported after BaseTransport on purpose: these submodules import from this
# package, so the definitions above must exist before they are pulled in.
from .http import HTTPTransport  # noqa: E402
from .local import LocalSpoolTransport  # noqa: E402
from .durable import DurableHTTPTransport  # noqa: E402

__all__ = [
    "BaseTransport",
    "DurableHTTPTransport",
    "Event",
    "HTTPTransport",
    "InMemoryTransport",
    "LocalSpoolTransport",
    "Transport",
]
