"""Local JSONL spool transport."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from . import BaseTransport, Event

_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


class LocalSpoolTransport(BaseTransport):
    """Append already-enveloped events to per-session JSONL spool files.

    This is intentionally only a durable local buffer. It does not attempt HTTP
    replay, pruning, or dead-letter handling; those belong in the later HTTP
    transport that talks to FastAPI.
    """

    def __init__(self, spool_dir: str | Path = ".promptetheus/spool") -> None:
        super().__init__()
        self.spool_dir = Path(spool_dir)
        self._pending: list[dict] = []

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def send_event(self, event: Event) -> None:
        self._ensure_open()
        self._pending.append(dict(event))

    def send_batch(self, events: Iterable[Event]) -> None:
        self._ensure_open()
        self._pending.extend(dict(event) for event in events)

    def flush(self, timeout: float | None = None) -> None:
        self._ensure_open()
        if not self._pending:
            return

        self.spool_dir.mkdir(parents=True, exist_ok=True)
        grouped = self._group_by_session(self._pending)

        for session_id, events in grouped.items():
            path = self.path_for_session(session_id)
            with path.open("a", encoding="utf-8") as file:
                for event in events:
                    file.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
                    file.write("\n")

        self._pending.clear()

    def path_for_session(self, session_id: object) -> Path:
        safe_session_id = _safe_filename(str(session_id or "unknown-session"))
        return self.spool_dir / f"{safe_session_id}.jsonl"

    @staticmethod
    def _group_by_session(events: list[dict]) -> dict[object, list[dict]]:
        grouped: dict[object, list[dict]] = {}
        for event in events:
            session_id = event.get("session_id") or "unknown-session"
            grouped.setdefault(session_id, []).append(event)
        return grouped


def _safe_filename(value: str) -> str:
    safe = _SAFE_FILENAME_CHARS.sub("_", value).strip("._")
    return safe or "unknown-session"
