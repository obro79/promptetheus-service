from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest

from promptetheus.config import Config
from promptetheus.server.mcp import PromptetheusAPIClient, resolve_mcp_config


def test_resolve_mcp_config_requires_api_key() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        resolve_mcp_config(Config())

    message = str(excinfo.value)
    assert "PROMPTETHEUS_API_KEY" in message
    assert "PROMPTETHEUS_API_URL" in message
    assert "override the hosted default" in message
    assert "database service-role keys" in message


def test_resolve_mcp_config_uses_promptetheus_api_config() -> None:
    config = resolve_mcp_config(
        Config(api_url="https://api.example.test/", api_key="pt_secret")
    )

    assert config.api_url == "https://api.example.test"
    assert config.api_key == "pt_secret"


def test_tool_request_posts_compact_json_and_adds_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"evidence": [{"id": "log-1"}]}).encode()

    def fake_urlopen(request: object, timeout: float) -> Response:
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["body"] = json.loads(request.data.decode())
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr("promptetheus.server.mcp.urlopen", fake_urlopen)
    client = PromptetheusAPIClient("https://api.example.test", "pt_secret", timeout=3)

    result = client.get_promptetheus_evidence(
        incident_id="inc_123",
        project_ref=None,
        session_id="sess_123",
        services=["api", "postgres", ""],
        limit=999,
    )

    assert seen["url"] == "https://api.example.test/mcp/promptetheus/evidence"
    assert seen["body"] == {
        "incident_id": "inc_123",
        "session_id": "sess_123",
        "services": ["api", "postgres"],
        "limit": 100,
    }
    assert seen["timeout"] == 3
    assert result["ok"] is True
    assert result["source"]["service"] == "promptetheus-hosted-api"
    assert result["evidence"] == [{"id": "log-1"}]


def test_http_error_becomes_safe_error_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float) -> object:
        raise HTTPError(
            url="https://api.example.test/mcp/fix-brief",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("promptetheus.server.mcp.urlopen", fake_urlopen)
    client = PromptetheusAPIClient("https://api.example.test", "pt_secret")

    result = client.get_fix_brief(incident_id="inc_123")

    assert result["ok"] is False
    assert result["status"] == 503
    assert result["error"]["type"] == "http_error"
    assert result["source"]["url"] == "https://api.example.test/mcp/fix-brief"


def test_unavailable_error_becomes_safe_error_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float) -> object:
        raise URLError("connection refused")

    monkeypatch.setattr("promptetheus.server.mcp.urlopen", fake_urlopen)
    client = PromptetheusAPIClient("https://api.example.test", "pt_secret")

    result = client.search_promptetheus_logs(
        service="postgres",
        query="permission denied",
        limit=999,
    )

    assert result["ok"] is False
    assert result["status"] is None
    assert result["error"]["type"] == "unavailable"
    assert result["source"]["url"] == "https://api.example.test/mcp/promptetheus/logs/search"


def test_promptetheus_advisors_includes_safe_type(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request: object, timeout: float) -> Response:
        seen["body"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr("promptetheus.server.mcp.urlopen", fake_urlopen)
    client = PromptetheusAPIClient("https://api.example.test", "pt_secret")

    client.get_promptetheus_advisors(advisor_type="performance", project_ref="abc123")

    assert seen["body"] == {"type": "performance", "project_ref": "abc123"}
