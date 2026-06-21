"""Hosted Promptetheus MCP server for incident-focused Promptetheus evidence.

This module is intentionally dependency-light at import time. The optional
``mcp`` package is imported only by ``run()``, so the base SDK can be imported
without installing ``promptetheus[mcp]``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from ..config import Config, load_config

_DEFAULT_TIMEOUT_SECONDS = 8.0
_MAX_LIMIT = 100


@dataclass(frozen=True)
class MCPConfig:
    """Resolved configuration for the hosted MCP tool layer."""

    api_url: str
    api_key: str


def resolve_mcp_config(config: Config | None = None) -> MCPConfig:
    """Resolve hosted API configuration from env/config and validate it."""

    resolved = config if config is not None else load_config()
    api_url = _coerce_nonempty_str(resolved.api_url)
    api_key = _coerce_nonempty_str(resolved.api_key)
    missing: list[str] = []
    if api_url is None:
        missing.append("PROMPTETHEUS_API_URL")
    if api_key is None:
        missing.append("PROMPTETHEUS_API_KEY")
    if missing:
        joined = " and ".join(missing)
        raise RuntimeError(
            f"promptetheus mcp requires {joined}. Set the hosted Promptetheus "
            "API key via environment variables or ~/.promptetheus/config.toml. "
            "Use PROMPTETHEUS_API_URL only to override the hosted default. "
            "Do not provide database service-role keys."
        )
    return MCPConfig(api_url=api_url.rstrip("/"), api_key=api_key)


class PromptetheusAPIClient:
    """Small stdlib HTTP client for hosted Promptetheus MCP endpoints."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.api_url = api_url.rstrip("/") + "/"
        self.api_key = api_key
        self.timeout = timeout

    def get_failure_context(
        self,
        *,
        incident_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        return self.post(
            "/mcp/failure-context",
            _compact_payload(
                {
                    "incident_id": incident_id,
                    "session_id": session_id,
                    "run_id": run_id,
                }
            ),
        )

    def get_promptetheus_evidence(
        self,
        *,
        incident_id: str | None = None,
        project_ref: str | None = None,
        session_id: str | None = None,
        services: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.post(
            "/mcp/promptetheus/evidence",
            _compact_payload(
                {
                    "incident_id": incident_id,
                    "project_ref": project_ref,
                    "session_id": session_id,
                    "services": _safe_services(services),
                    "limit": _safe_limit(limit),
                }
            ),
        )

    def search_promptetheus_logs(
        self,
        *,
        service: str,
        query: str | None = None,
        project_ref: str | None = None,
        incident_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.post(
            "/mcp/promptetheus/logs/search",
            _compact_payload(
                {
                    "service": service,
                    "query": query,
                    "project_ref": project_ref,
                    "incident_id": incident_id,
                    "start_time": start_time,
                    "end_time": end_time,
                    "limit": _safe_limit(limit),
                }
            ),
        )

    def get_promptetheus_advisors(
        self,
        *,
        advisor_type: str = "security",
        project_ref: str | None = None,
        incident_id: str | None = None,
    ) -> dict[str, Any]:
        return self.post(
            "/mcp/promptetheus/advisors",
            _compact_payload(
                {
                    "type": _safe_advisor_type(advisor_type),
                    "project_ref": project_ref,
                    "incident_id": incident_id,
                }
            ),
        )

    def get_fix_brief(
        self,
        *,
        incident_id: str | None = None,
        session_id: str | None = None,
        include_evidence: bool = True,
    ) -> dict[str, Any]:
        return self.post(
            "/mcp/fix-brief",
            _compact_payload(
                {
                    "incident_id": incident_id,
                    "session_id": session_id,
                    "include_evidence": bool(include_evidence),
                }
            ),
        )

    def post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """POST a JSON payload and convert failures to compact tool results."""

        source = self._source(path, method="POST")
        body = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        request = Request(
            urljoin(self.api_url, path.lstrip("/")),
            data=body,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
        except HTTPError as exc:
            detail = _decode_body(exc.read())
            parsed = _parse_json(detail)
            return {
                "ok": False,
                "status": exc.code,
                "source": source,
                "error": {
                    "type": "http_error",
                    "message": _extract_error_message(parsed, detail),
                },
            }
        except (TimeoutError, URLError, OSError) as exc:
            return {
                "ok": False,
                "status": None,
                "source": source,
                "error": {
                    "type": "unavailable",
                    "message": str(exc) or exc.__class__.__name__,
                },
            }
        except Exception as exc:  # pragma: no cover - defensive MCP boundary
            return {
                "ok": False,
                "status": None,
                "source": source,
                "error": {
                    "type": "unexpected_error",
                    "message": str(exc) or exc.__class__.__name__,
                },
            }

        text = _decode_body(raw)
        parsed = _parse_json(text)
        if parsed is None and text:
            return {
                "ok": False,
                "status": status,
                "source": source,
                "error": {
                    "type": "invalid_json",
                    "message": "Promptetheus API returned a non-JSON response.",
                },
            }
        if isinstance(parsed, Mapping):
            result = dict(parsed)
            result.setdefault("ok", 200 <= status < 300)
            result.setdefault("status", status)
            result.setdefault("source", source)
            return _json_safe(result)
        return {
            "ok": 200 <= status < 300,
            "status": status,
            "source": source,
            "data": _json_safe(parsed),
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "promptetheus-mcp/0.0.1",
            "X-Promptetheus-Client": "mcp",
        }

    def _source(self, path: str, *, method: str) -> dict[str, str]:
        return {
            "service": "promptetheus-hosted-api",
            "method": method,
            "url": urljoin(self.api_url, path.lstrip("/")),
        }


def run() -> None:
    """Run the read-only Promptetheus MCP server over stdio."""

    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "promptetheus mcp requires the optional MCP dependencies. Install "
            "them with: pip install 'promptetheus[mcp]'."
        ) from exc

    config = resolve_mcp_config()
    client = PromptetheusAPIClient(config.api_url, config.api_key)
    server = FastMCP("promptetheus")

    @server.tool()
    def get_failure_context(
        incident_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Return compact trace context for a failed incident/run/session."""

        return client.get_failure_context(
            incident_id=incident_id,
            session_id=session_id,
            run_id=run_id,
        )

    @server.tool()
    def get_promptetheus_evidence(
        incident_id: str | None = None,
        project_ref: str | None = None,
        session_id: str | None = None,
        services: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Return hosted Promptetheus evidence for an incident without direct DB keys."""

        return client.get_promptetheus_evidence(
            incident_id=incident_id,
            project_ref=project_ref,
            session_id=session_id,
            services=services,
            limit=limit,
        )

    @server.tool()
    def search_promptetheus_logs(
        service: str,
        query: str | None = None,
        project_ref: str | None = None,
        incident_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search hosted Promptetheus logs related to an incident or project."""

        return client.search_promptetheus_logs(
            service=service,
            query=query,
            project_ref=project_ref,
            incident_id=incident_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    @server.tool()
    def get_promptetheus_advisors(
        advisor_type: str = "security",
        project_ref: str | None = None,
        incident_id: str | None = None,
    ) -> dict[str, Any]:
        """Return hosted Promptetheus advisor findings relevant to an incident/project."""

        return client.get_promptetheus_advisors(
            advisor_type=advisor_type,
            project_ref=project_ref,
            incident_id=incident_id,
        )

    @server.tool()
    def get_fix_brief(
        incident_id: str | None = None,
        session_id: str | None = None,
        include_evidence: bool = True,
    ) -> dict[str, Any]:
        """Return a compact repair brief with provenance-linked evidence."""

        return client.get_fix_brief(
            incident_id=incident_id,
            session_id=session_id,
            include_evidence=include_evidence,
        )

    server.run(transport="stdio")


def _coerce_nonempty_str(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text.strip() or None


def _compact_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _safe_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        return 20
    return max(1, min(limit, _MAX_LIMIT))


def _safe_services(services: list[str] | None) -> list[str] | None:
    if services is None:
        return None
    cleaned = [
        service.strip()
        for service in services
        if isinstance(service, str) and service.strip()
    ]
    return cleaned[:10] or None


def _safe_advisor_type(advisor_type: str) -> str:
    return advisor_type if advisor_type in {"security", "performance"} else "security"


def _decode_body(body: bytes | str) -> str:
    if isinstance(body, str):
        return body
    return body.decode("utf-8", errors="replace")


def _parse_json(text: str) -> Any | None:
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_error_message(parsed: Any | None, fallback: str) -> str:
    if isinstance(parsed, Mapping):
        for key in ("message", "error", "detail"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value
    return fallback or "Promptetheus API request failed."


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value
