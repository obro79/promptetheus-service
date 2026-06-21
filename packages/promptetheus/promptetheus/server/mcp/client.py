"""HTTP client for the Promptetheus MCP server.

The MCP server is a thin client of the FastAPI gateway, not a second backend.
This module wraps the small slice of the locked API the incident-context tools
need, authenticating with a console/Supabase-session bearer token and returning
parsed JSON. It never re-implements workspace/project scoping or redaction — FastAPI
owns both.

Configuration comes from the environment:

- ``PROMPTETHEUS_API_URL`` — gateway base URL (default ``http://localhost:4318``).
- ``PROMPTETHEUS_API_KEY`` — project API key. This is enough for project-scoped
  MCP reads.
- ``PROMPTETHEUS_CONSOLE_TOKEN`` — optional console token for owner-only tools.

httpx is imported lazily inside the client so importing this module (or the
package) never requires the optional ``mcp`` extra to be installed.
"""

from __future__ import annotations

import os
from typing import Any

from promptetheus.server.auth import DEV_CONSOLE_TOKEN

DEFAULT_API_URL = "http://localhost:4318"


class PromptetheusAPIError(RuntimeError):
    """Raised when the gateway returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Promptetheus API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class PromptetheusClient:
    """Thin authenticated HTTP client over the Promptetheus FastAPI gateway.

    Args:
        base_url: Gateway base URL. Defaults to ``PROMPTETHEUS_API_URL`` or
            ``http://localhost:4318``. Ignored when http_client is supplied.
        console_token: Console bearer token. Defaults to
            ``PROMPTETHEUS_CONSOLE_TOKEN``. Use this for owner-only tools.
        api_key: Project API key. Defaults to ``PROMPTETHEUS_API_KEY``. This is
            enough for project-scoped MCP read tools.
        http_client: Optional pre-built synchronous httpx-style client. Tests
            inject a Starlette ``TestClient`` (itself a sync httpx client wired to
            an in-process FastAPI app); production builds its own.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        console_token: str | None = None,
        http_client: Any = None,
        timeout: float = 30.0,
    ) -> None:
        resolved_url = (
            base_url or os.environ.get("PROMPTETHEUS_API_URL") or DEFAULT_API_URL
        )
        self._base_url = resolved_url.rstrip("/")
        resolved_token = (
            console_token
            if console_token is not None
            else os.environ.get("PROMPTETHEUS_CONSOLE_TOKEN")
        )
        if resolved_token is None:
            resolved_token = api_key or os.environ.get("PROMPTETHEUS_API_KEY")
        if resolved_token is None and http_client is not None:
            resolved_token = DEV_CONSOLE_TOKEN
        if not resolved_token:
            raise RuntimeError(
                "PROMPTETHEUS_API_KEY is required to start the Promptetheus MCP "
                "server for project-scoped reads. Set PROMPTETHEUS_CONSOLE_TOKEN "
                "only when owner-only tools are needed."
            )
        self._console_token = resolved_token
        self._timeout = timeout
        self._client: Any = http_client

    def _http(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                base_url=self._base_url, timeout=self._timeout
            )
        return self._client

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        # Auth is applied per-request so an injected client need not carry it.
        response = self._http().request(
            method,
            path,
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {self._console_token}"},
        )
        if response.status_code // 100 != 2:
            raise PromptetheusAPIError(response.status_code, _detail(response))
        return response.json()

    # -- read tools ----------------------------------------------------------

    def get_incident(self, incident_id: str) -> dict[str, Any]:
        body = self._request("GET", f"/api/incidents/{incident_id}")
        return dict(body.get("incident") or {})

    def get_incident_context(self, incident_id: str) -> dict[str, Any]:
        body = self._request("GET", f"/api/incidents/{incident_id}/context")
        return dict(body.get("context") or {})

    def get_trace_events(self, trace_id: str) -> list[dict[str, Any]]:
        body = self._request("GET", f"/api/traces/{trace_id}/events")
        return list(body.get("events") or [])

    def search_incidents(self, query: str) -> list[dict[str, Any]]:
        body = self._request("GET", "/api/incidents", params={"q": query})
        return list(body.get("incidents") or [])

    def get_connected_repo(self, project_id: str) -> dict[str, Any]:
        body = self._request("GET", f"/api/projects/{project_id}/connected-repo")
        return dict(body.get("connected_repo") or {})

    # -- write tool ----------------------------------------------------------

    def link_pr_to_incident(self, incident_id: str, pr_url: str) -> dict[str, Any]:
        body = self._request(
            "POST", f"/api/incidents/{incident_id}/pr-link", json={"pr_url": pr_url}
        )
        return dict(body.get("incident") or {})

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def _detail(response: Any) -> str:
    """Pull a human-readable error detail from a response. Never raises."""

    try:
        payload = response.json()
    except Exception:
        return (getattr(response, "text", "") or "request failed").strip()
    if isinstance(payload, dict) and payload.get("detail") is not None:
        return str(payload["detail"])
    return str(payload)


__all__ = ["PromptetheusAPIError", "PromptetheusClient"]
