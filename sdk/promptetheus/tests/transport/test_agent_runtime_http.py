from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest

from promptetheus.agent_runtime import AgentRuntime
from promptetheus.config import Config, DEFAULT_API_URL, override_config, reset_config


class _Response:
    def __init__(self, body: object = None):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        if self.body is None:
            return b""
        if isinstance(self.body, bytes):
            return self.body
        return json.dumps(self.body).encode("utf-8")


class _Recorder:
    def __init__(self, response: object = None, exc: BaseException | None = None):
        self.response = response
        self.exc = exc
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if self.exc is not None:
            raise self.exc
        return _Response(self.response)

    def only(self):
        assert len(self.requests) == 1
        return self.requests[0]


def _json_body(request) -> dict:
    assert request.data is not None
    return json.loads(request.data.decode("utf-8"))


def _headers(request) -> dict[str, str]:
    return dict(request.header_items())


def _runtime(
    session_id: str = "sess_1",
    *,
    endpoint: str = "http://example.test",
    api_key: str = "pt_secret",
) -> AgentRuntime:
    return AgentRuntime(session_id, endpoint=endpoint, api_key=api_key)


def test_remember_posts_redacted_memory(monkeypatch):
    recorder = _Recorder({})
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)
    runtime = AgentRuntime(
        "sess/a",
        endpoint="http://example.test",
        api_key="pt_secret",
        timeout=1.25,
    )

    runtime.remember(
        "hypothesis",
        {
            "note": "token sk-ABCDEFabcdef0123456789",
            "api_key": "sk-SECRETabcdef0123456789",
        },
        metadata={"source": "agent"},
    )

    request, timeout = recorder.only()
    assert request.full_url == "http://example.test/api/traces/sess%2Fa/runtime/memory"
    assert request.get_method() == "POST"
    assert timeout == 1.25
    headers = _headers(request)
    assert headers["Authorization"] == "Bearer pt_secret"
    assert headers["Content-type"] == "application/json"
    body = _json_body(request)
    assert body["kind"] == "hypothesis"
    assert body["metadata"] == {"source": "agent"}
    assert "sk-ABCDEF" not in body["value"]["note"]
    assert body["value"]["api_key"] == "[REDACTED]"


def test_endpoint_with_api_suffix_does_not_duplicate_api(monkeypatch):
    recorder = _Recorder({"memory": []})
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)

    runtime = _runtime(endpoint="http://example.test/api")
    runtime.get_memory()

    request, _timeout = recorder.only()
    assert request.full_url == "http://example.test/api/traces/sess_1/runtime/memory?limit=20"


def test_get_memory_parses_memory_entries(monkeypatch):
    recorder = _Recorder({"memory": [{"kind": "hypothesis"}, "bad"]})
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)

    runtime = _runtime()

    assert runtime.get_memory(limit=2) == [{"kind": "hypothesis"}]
    request, _timeout = recorder.only()
    assert request.get_method() == "GET"
    assert request.data is None
    assert request.full_url.endswith("/runtime/memory?limit=2")


def test_record_tool_call_returns_dedupe_response(monkeypatch):
    recorder = _Recorder({"seen_recently": True, "hint": "change hypothesis"})
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)
    runtime = _runtime()

    result = runtime.record_tool_call(
        "pytest",
        command="pytest tests/server",
        args={"token": "Bearer abc.def.ghi"},
        status="failed",
        error="boom",
    )

    assert result == {"seen_recently": True, "hint": "change hypothesis"}
    body = _json_body(recorder.only()[0])
    assert body["tool_name"] == "pytest"
    assert body["command"] == "pytest tests/server"
    assert body["status"] == "failed"
    assert body["args"]["token"] == "[REDACTED]"


def test_before_tool_call_returns_runtime_hint(monkeypatch):
    hint = {"kind": "repeated_tool_failure", "message": "change hypothesis"}
    recorder = _Recorder({"seen_recently": True, "attempt_count": 2, "hint": hint})
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)
    runtime = _runtime()

    result = runtime.before_tool_call(
        "pytest",
        command="pytest tests/server",
        args={"path": "tests/server"},
        metadata={"phase": "verify"},
    )

    assert result["seen_recently"] is True
    assert result["attempt_count"] == 2
    assert result["hint"] == hint
    request, _timeout = recorder.only()
    assert request.full_url == "http://example.test/api/traces/sess_1/runtime/tool-call"
    body = _json_body(request)
    assert body == {
        "tool_name": "pytest",
        "command": "pytest tests/server",
        "args": {"path": "tests/server"},
        "status": "planned",
        "metadata": {"phase": "verify"},
    }


def test_after_tool_call_records_failure_and_success(monkeypatch):
    recorder = _Recorder({"seen_recently": False, "hint": None})
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)
    runtime = _runtime()

    failure = runtime.after_tool_call(
        "pytest",
        command="pytest tests/server",
        args={"path": "tests/server"},
        error="assertion failed",
    )
    success = runtime.after_tool_call(
        "pytest",
        command="pytest tests/server",
        args={"path": "tests/server"},
    )

    assert failure == {"seen_recently": False, "hint": None}
    assert success == {"seen_recently": False, "hint": None}
    assert len(recorder.requests) == 2
    failure_body = _json_body(recorder.requests[0][0])
    success_body = _json_body(recorder.requests[1][0])
    assert failure_body["status"] == "failed"
    assert failure_body["error"] == "assertion failed"
    assert success_body["status"] == "succeeded"
    assert "error" not in success_body


def test_after_tool_call_respects_explicit_status(monkeypatch):
    recorder = _Recorder({})
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)
    runtime = _runtime()

    runtime.after_tool_call("shell", status="cancelled")

    assert _json_body(recorder.only()[0])["status"] == "cancelled"


def test_heartbeat_posts_live_state(monkeypatch):
    recorder = _Recorder({})
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)
    runtime = _runtime()

    runtime.heartbeat(
        phase="debugging",
        current_file="server/app.py",
        current_hypothesis="auth token is missing",
    )

    request, _timeout = recorder.only()
    assert request.full_url == "http://example.test/api/traces/sess_1/runtime/heartbeat"
    assert _json_body(request) == {
        "phase": "debugging",
        "current_file": "server/app.py",
        "current_hypothesis": "auth token is missing",
    }


def test_next_hint_parses_hint(monkeypatch):
    recorder = _Recorder({"hint": {"message": "try a new test"}})
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)
    runtime = _runtime()

    assert runtime.next_hint() == {"message": "try a new test"}
    request, _timeout = recorder.only()
    assert request.get_method() == "GET"
    assert request.full_url == "http://example.test/api/traces/sess_1/runtime/hint"


@pytest.mark.parametrize(
    "exc",
    [
        URLError("offline"),
        HTTPError("http://example.test", 404, "not found", hdrs=None, fp=None),
        TimeoutError("slow"),
    ],
)
def test_runtime_failures_are_safe_fallbacks(monkeypatch, exc):
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", _Recorder(exc=exc))
    runtime = _runtime()

    runtime.remember("hypothesis", {"x": 1})
    runtime.heartbeat(phase="debugging")
    assert runtime.get_memory() == []
    assert runtime.record_tool_call("pytest") == {"seen_recently": False, "hint": None}
    assert runtime.before_tool_call("pytest") == {"seen_recently": False, "hint": None}
    assert runtime.after_tool_call("pytest") == {"seen_recently": False, "hint": None}
    assert runtime.next_hint() is None


def test_malformed_json_is_safe_fallback(monkeypatch):
    recorder = _Recorder(b"not-json")
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)
    runtime = _runtime()

    assert runtime.get_memory() == []
    assert runtime.next_hint() is None


def test_missing_api_key_makes_no_http_calls(monkeypatch):
    monkeypatch.delenv("PROMPTETHEUS_API_URL", raising=False)
    monkeypatch.delenv("PROMPTETHEUS_API_KEY", raising=False)
    reset_config()
    recorder = _Recorder({})
    monkeypatch.setattr("promptetheus.agent_runtime.urlopen", recorder)

    with override_config(Config()):
        runtime = AgentRuntime("sess_1")
        runtime.remember("hypothesis", {"x": 1})
        assert runtime.get_memory() == []
        assert runtime.record_tool_call("pytest") == {"seen_recently": False, "hint": None}
        assert runtime.before_tool_call("pytest") == {"seen_recently": False, "hint": None}
        assert runtime.after_tool_call("pytest") == {"seen_recently": False, "hint": None}
        assert runtime.next_hint() is None

    assert recorder.requests == []
    reset_config()


def test_hosted_default_endpoint_is_used_with_api_key(monkeypatch):
    monkeypatch.delenv("PROMPTETHEUS_API_URL", raising=False)
    monkeypatch.setenv("PROMPTETHEUS_API_KEY", "pt_env_key")
    reset_config()

    runtime = AgentRuntime("sess_1")

    assert runtime.endpoint == DEFAULT_API_URL
    assert runtime.api_key == "pt_env_key"
    reset_config()


def test_config_resolution_precedence(monkeypatch):
    monkeypatch.setenv("PROMPTETHEUS_API_URL", "http://env.test")
    monkeypatch.setenv("PROMPTETHEUS_API_KEY", "env_key")

    with override_config(Config(api_url="http://config.test", api_key="config_key")):
        env_runtime = AgentRuntime("sess_1")
        explicit_runtime = AgentRuntime(
            "sess_1",
            endpoint="http://explicit.test",
            api_key="explicit_key",
        )

    assert env_runtime.endpoint == "http://env.test"
    assert env_runtime.api_key == "env_key"
    assert explicit_runtime.endpoint == "http://explicit.test"
    assert explicit_runtime.api_key == "explicit_key"
    reset_config()


def test_api_key_not_leaked_in_failure_logs(monkeypatch, caplog):
    monkeypatch.setattr(
        "promptetheus.agent_runtime.urlopen",
        _Recorder(exc=URLError("offline")),
    )
    runtime = AgentRuntime(
        "sess_1",
        endpoint="http://example.test",
        api_key="pt_live_super_secret",
    )

    with caplog.at_level("DEBUG", logger="promptetheus"):
        runtime.remember("hypothesis", {"x": 1})

    assert "pt_live_super_secret" not in caplog.text
