"""Best-effort client for planned Promptetheus agent runtime endpoints.

The SDK never talks to Redis directly. AgentRuntime calls FastAPI runtime
coordination endpoints when they exist; the service owns the backing runtime
store. All methods are best-effort so instrumented agents keep running when the
service is offline or the runtime endpoints have not been deployed yet.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .config import get_config
from .redaction import build_default_redactor

logger = logging.getLogger("promptetheus")

_DEFAULT_TIMEOUT_SECONDS = 2.0
_DEFAULT_MEMORY_LIMIT = 20


def _coerce_nonempty_str(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text or None


def _resolve_endpoint(endpoint: str | None) -> str | None:
    explicit = _coerce_nonempty_str(endpoint)
    if explicit is not None:
        return explicit.rstrip("/")
    env = _coerce_nonempty_str(os.environ.get("PROMPTETHEUS_API_URL"))
    if env is not None:
        return env.rstrip("/")
    configured = _coerce_nonempty_str(get_config().api_url)
    return configured.rstrip("/") if configured is not None else None


def _resolve_api_key(api_key: str | None) -> str | None:
    explicit = _coerce_nonempty_str(api_key)
    if explicit is not None:
        return explicit
    env = _coerce_nonempty_str(os.environ.get("PROMPTETHEUS_API_KEY"))
    if env is not None:
        return env
    return _coerce_nonempty_str(get_config().api_key)


def _mapping_or_empty(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _safe_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        return _DEFAULT_MEMORY_LIMIT
    return max(1, min(limit, 200))


class AgentRuntime:
    """Forward-compatible client for live agent runtime coordination.

    The runtime surface is intentionally separate from trace transport. Trace
    events remain canonical and durable; runtime calls are short-lived guidance
    and coordination signals backed by the service. Every method swallows
    transport, serialization, and response parsing failures.
    """

    def __init__(
        self,
        session_id: str,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        enabled: bool = True,
    ) -> None:
        self.session_id = str(session_id)
        self.api_key = _resolve_api_key(api_key)
        self.endpoint = _resolve_endpoint(endpoint) if enabled and self.api_key else None
        self.timeout = float(timeout)
        self._redactor = build_default_redactor()

    def remember(
        self,
        kind: str,
        value: Any,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Store a short-lived runtime memory entry for this session."""

        payload = self._redact_payload(
            {
                "kind": str(kind),
                "value": value,
                "metadata": _mapping_or_empty(metadata),
            }
        )
        self._request("POST", self._session_path("/runtime/memory"), payload=payload)

    def get_memory(self, limit: int = _DEFAULT_MEMORY_LIMIT) -> list[dict[str, Any]]:
        """Return recent runtime memory entries, or [] when unavailable."""

        response = self._request(
            "GET",
            self._session_path("/runtime/memory"),
            query={"limit": str(_safe_limit(limit))},
        )
        if isinstance(response, list):
            return [dict(item) for item in response if isinstance(item, Mapping)]
        if isinstance(response, Mapping):
            raw = response.get("memory", response.get("entries", []))
            if isinstance(raw, list):
                return [dict(item) for item in raw if isinstance(item, Mapping)]
        return []

    def record_tool_call(
        self,
        tool_name: str,
        *,
        command: str | None = None,
        args: Mapping[str, Any] | None = None,
        status: str | None = None,
        error: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a tool/action attempt and return dedupe guidance when present."""

        payload: dict[str, Any] = {"tool_name": str(tool_name)}
        if command is not None:
            payload["command"] = str(command)
        if args is not None:
            payload["args"] = _mapping_or_empty(args)
        if status is not None:
            payload["status"] = str(status)
        if error is not None:
            payload["error"] = str(error)
        if metadata is not None:
            payload["metadata"] = _mapping_or_empty(metadata)

        response = self._request(
            "POST",
            self._session_path("/runtime/tool-call"),
            payload=self._redact_payload(payload),
        )
        if isinstance(response, Mapping):
            result = dict(response)
            result.setdefault("seen_recently", False)
            result.setdefault("hint", None)
            return result
        return {"seen_recently": False, "hint": None}

    def before_tool_call(
        self,
        tool_name: str,
        *,
        command: str | None = None,
        args: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ask the runtime for guidance before running a tool/action."""

        return self.record_tool_call(
            tool_name,
            command=command,
            args=args,
            status="planned",
            metadata=metadata,
        )

    def after_tool_call(
        self,
        tool_name: str,
        *,
        command: str | None = None,
        args: Mapping[str, Any] | None = None,
        status: str | None = None,
        error: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Report a completed tool/action outcome to the runtime."""

        resolved_status = status
        if resolved_status is None:
            resolved_status = "failed" if error is not None else "succeeded"
        return self.record_tool_call(
            tool_name,
            command=command,
            args=args,
            status=resolved_status,
            error=error,
            metadata=metadata,
        )

    def heartbeat(
        self,
        *,
        phase: str | None = None,
        current_file: str | None = None,
        current_hypothesis: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Publish live runtime state for this session."""

        payload: dict[str, Any] = {}
        if phase is not None:
            payload["phase"] = str(phase)
        if current_file is not None:
            payload["current_file"] = str(current_file)
        if current_hypothesis is not None:
            payload["current_hypothesis"] = str(current_hypothesis)
        if metadata is not None:
            payload["metadata"] = _mapping_or_empty(metadata)
        self._request(
            "POST",
            self._session_path("/runtime/heartbeat"),
            payload=self._redact_payload(payload),
        )

    def next_hint(self) -> Any | None:
        """Return the next runtime hint for the agent, or None when unavailable."""

        response = self._request("GET", self._session_path("/runtime/hint"))
        if not isinstance(response, Mapping):
            return None
        if "hint" in response:
            return response.get("hint")
        if any(key in response for key in ("message", "action", "severity")):
            return dict(response)
        return None

    def _session_path(self, suffix: str) -> str:
        return f"/api/traces/{quote(self.session_id, safe='')}{suffix}"

    def _url(self, path: str, query: Mapping[str, str] | None = None) -> str | None:
        if self.endpoint is None:
            return None
        clean_path = path.lstrip("/")
        if self.endpoint.endswith("/api") and clean_path.startswith("api/"):
            clean_path = clean_path[4:]
        url = f"{self.endpoint}/{clean_path}"
        if query:
            url = f"{url}?{urlencode(dict(query))}"
        return url

    def _headers(self, *, json_body: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        query: Mapping[str, str] | None = None,
    ) -> Any | None:
        url = self._url(path, query)
        if url is None:
            return None

        try:
            body = None
            json_body = method != "GET"
            if json_body:
                body = json.dumps(dict(payload or {}), default=str).encode("utf-8")
            request = Request(
                url,
                data=body,
                headers=self._headers(json_body=json_body),
                method=method,
            )
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read()
            if not response_body:
                return {}
            return json.loads(response_body.decode("utf-8"))
        except (HTTPError, URLError, OSError, TimeoutError, TypeError, ValueError):
            logger.debug("Promptetheus agent runtime request failed", exc_info=True)
            return None
        except Exception:
            logger.debug(
                "Promptetheus agent runtime request failed unexpectedly",
                exc_info=True,
            )
            return None

    def _redact_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            event = {
                "type": "state_change",
                "session_id": self.session_id,
                "timestamp": "1970-01-01T00:00:00Z",
                "seq": 0,
                "idempotency_key": f"{self.session_id}:runtime:0",
                "payload": dict(payload),
            }
            redacted = self._redactor(event)
            out = redacted.get("payload", {}) if isinstance(redacted, Mapping) else {}
            return dict(out) if isinstance(out, Mapping) else {}
        except Exception:
            logger.debug("Promptetheus agent runtime redaction failed", exc_info=True)
            return dict(payload)


__all__ = ["AgentRuntime"]
