"""Tests for the Devin fix runner.

The runner must:
- fall back to the deterministic runner when DEVIN_API_KEY is absent,
- create + poll a Devin session and return its structured {diagnosis, plan, diff}
  as a non-fallback FixAgentResult,
- inject similar past fixes from Redis memory as advanced context in the prompt,
- reject (fall back on) a diff that escapes the runner's allowed paths.

A fake httpx module is injected so no network/key is needed.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from promptetheus.server.fix_agent import memory
from promptetheus.server.fix_agent.runners.devin import DevinRunner


def _bundle() -> dict:
    return {
        "incident": {
            "id": "incident_ws_dev_browser_goal_mismatch",
            "workspace_id": "ws_dev",
            "project_id": "proj_dev",
            "label": "browser_goal_mismatch",
            "severity": "high",
            "confidence": 0.9,
        },
        "user_goal": "Book a 30 minute AcmeMeet with Dana on Tuesday at 2pm",
        "root_cause": "The booking step selected the wrong slot.",
        "events": [{"seq": 3}],
        "allowed_paths": ["agents/"],
        "source": "browserbase",
    }


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, structured_output: dict[str, Any], calls: list[dict[str, Any]]) -> None:
        self._output = structured_output
        self._calls = calls

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def post(self, path: str, json: dict[str, Any]) -> _FakeResponse:
        self._calls.append({"path": path, "json": json})
        return _FakeResponse({"session_id": "devin-123", "url": "https://app.devin.ai/s/devin-123"})

    def get(self, path: str) -> _FakeResponse:
        return _FakeResponse({"status": "finished", "structured_output": self._output})


def _install_fake_httpx(monkeypatch, structured_output: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class _FakeHttpx:
        @staticmethod
        def Client(*args: Any, **kwargs: Any) -> _FakeClient:
            return _FakeClient(structured_output, calls)

    monkeypatch.setenv("DEVIN_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "httpx", _FakeHttpx)
    return calls


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(memory, "_client", None, raising=False)
    monkeypatch.setattr(memory, "_client_resolved", True, raising=False)


def test_falls_back_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("DEVIN_API_KEY", raising=False)
    result = DevinRunner(allowed_paths=["agents/"]).run(_bundle())
    assert result.fallback is True
    assert result.runner == "deterministic"


def test_returns_devin_structured_fix(monkeypatch) -> None:
    diff = "--- /dev/null\n+++ b/agents/guard.py\n@@ -0,0 +1,1 @@\n+assert True\n"
    calls = _install_fake_httpx(
        monkeypatch,
        {"diagnosis": "wrong slot", "plan": ["add guard"], "diff": diff},
    )

    result = DevinRunner(allowed_paths=["agents/"]).run(_bundle())

    assert result.fallback is False
    assert result.runner == "devin"
    assert result.changed_files == ["agents/guard.py"]
    assert result.metadata["session_id"] == "devin-123"
    # The created session carried the structured-output schema + tags.
    body = calls[0]["json"]
    assert body["structured_output_schema"]["required"] == ["diagnosis", "plan", "diff"]
    assert "promptetheus" in body["tags"]


def test_injects_similar_fixes_as_advanced_context(monkeypatch) -> None:
    diff = "--- /dev/null\n+++ b/agents/guard.py\n@@ -0,0 +1,1 @@\n+assert True\n"
    calls = _install_fake_httpx(
        monkeypatch,
        {"diagnosis": "d", "plan": ["p"], "diff": diff},
    )
    monkeypatch.setattr(
        memory,
        "find_similar_fixes",
        lambda bundle: [{"from_incident_id": "old_1", "plan": ["reuse me"], "score": 0.91}],
    )

    result = DevinRunner(allowed_paths=["agents/"]).run(_bundle())

    assert result.metadata["similar_fix_count"] == 1
    assert result.metadata["similar_fix_ids"] == ["old_1"]
    prompt = calls[0]["json"]["prompt"]
    assert "Advanced context" in prompt
    assert "reuse me" in prompt


def test_falls_back_on_path_escape(monkeypatch) -> None:
    diff = "--- /dev/null\n+++ b/infra/secrets.py\n@@ -0,0 +1,1 @@\n+assert True\n"
    _install_fake_httpx(monkeypatch, {"diagnosis": "d", "plan": ["p"], "diff": diff})

    result = DevinRunner(allowed_paths=["agents/"]).run(_bundle())

    # The diff escapes agents/ -> hard security stop -> deterministic fallback.
    assert result.fallback is True
    assert result.runner == "deterministic"


def test_falls_back_on_empty_diff(monkeypatch) -> None:
    _install_fake_httpx(monkeypatch, {"diagnosis": "d", "plan": ["p"], "diff": ""})

    result = DevinRunner(allowed_paths=["agents/"]).run(_bundle())

    assert result.fallback is True
    assert result.runner == "deterministic"
