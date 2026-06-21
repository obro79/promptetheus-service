"""Dependency-free HTTP transport for the Promptetheus FastAPI contract."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from promptetheus.config import get_config

from . import BaseTransport, Event

class HTTPTransport(BaseTransport):
    """Send already-enveloped events to a Promptetheus FastAPI endpoint."""

    def __init__(
        self, endpoint: str, api_key: str | None = None, timeout: float | None = None
    ) -> None:
        super().__init__()
        self.endpoint = endpoint.rstrip("/") + "/"
        self.api_key = api_key
        self.timeout = float(timeout if timeout is not None else get_config().http_timeout)

    def create_trace(self, metadata: Mapping[str, Any]) -> None:
        self._post("/api/traces", dict(metadata))

    def send_event(self, event: Event) -> None:
        self.send_batch([event])

    def send_batch(self, events: Iterable[Event]) -> None:
        self._ensure_open()
        materialized = [dict(event) for event in events]
        if not materialized:
            return
        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in materialized:
            grouped.setdefault(str(event["session_id"]), []).append(event)
        for session_id, session_events in grouped.items():
            self._post(f"/api/traces/{session_id}/events", {"events": session_events})

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            urljoin(self.endpoint, path.lstrip("/")),
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Promptetheus HTTP {exc.code}: {detail}") from exc
        if not response_body:
            return {}
        return json.loads(response_body.decode("utf-8"))

    def upload_artifact(
        self,
        session_id: str,
        *,
        body: bytes,
        content_type: str,
        filename: str | None = None,
        artifact_type: str | None = None,
    ) -> dict[str, Any]:
        """Upload artifact bytes through FastAPI.

        Bytes are sent as the request body. Artifact metadata rides in headers
        so the server does not need multipart parsing dependencies.
        """

        self._ensure_open()
        headers = {
            "Content-Type": content_type,
            "Accept": "application/json",
            "X-Promptetheus-Filename": filename or "artifact.bin",
            "X-Promptetheus-Size-Bytes": str(len(body)),
        }
        if artifact_type is not None:
            headers["X-Promptetheus-Artifact-Type"] = artifact_type
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            urljoin(
                self.endpoint,
                f"/api/traces/{session_id}/artifacts".lstrip("/"),
            ),
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Promptetheus HTTP {exc.code}: {detail}") from exc

        result = json.loads(response_body.decode("utf-8")) if response_body else {}
        artifact = result.get("artifact") if isinstance(result, dict) else result
        if not isinstance(artifact, dict):
            raise RuntimeError("artifact upload response missing artifact row")
        return {
            "artifact_id": artifact["artifact_id"],
            "storage_path": artifact.get("storage_path", ""),
        }

    def _create_artifact_metadata(
        self,
        session_id: str,
        *,
        body: bytes,
        content_type: str,
        filename: str | None = None,
        artifact_type: str | None = None,
    ) -> dict[str, Any]:
        """Create an artifact metadata row without uploading bytes.

        Kept private for tests or future migration work; public SDK upload
        must not use it until the server accepts the corresponding bytes.
        """

        payload: dict[str, Any] = {
            "content_type": content_type,
            "size_bytes": len(body),
            "filename": filename or "artifact.bin",
        }
        if artifact_type is not None:
            payload["artifact_type"] = artifact_type
        result = self._post(f"/api/traces/{session_id}/artifacts", payload)
        artifact = result.get("artifact") if isinstance(result, dict) else result
        if not isinstance(artifact, dict):
            raise RuntimeError("artifact upload response missing artifact row")
        return {
            "artifact_id": artifact["artifact_id"],
            "storage_path": artifact.get("storage_path", ""),
        }
