import pytest

import promptetheus as pt
from promptetheus import config as config_module
from promptetheus.config import DEFAULT_API_URL, DEFAULT_HTTP_TIMEOUT
from promptetheus.trace import resolve_transport
from promptetheus.transport import DurableHTTPTransport, InMemoryTransport, LocalSpoolTransport


class RecordingTransport:
    def __init__(self):
        self.events = []
        self.flushed = False

    def send_event(self, event):
        self.events.append(event)

    def flush(self, timeout=None):
        self.flushed = True


def test_observe_records_function_boundary_and_session_end():
    transport = RecordingTransport()

    @pt.observe(agent="demo-agent", user_goal="do the task", transport=transport)
    def run_agent(x):
        pt.current().agent_message("working")
        return x + 1

    assert run_agent(1) == 2

    event_types = [event["type"] for event in transport.events]
    assert event_types[0] == "state_change"
    assert "tool_call" in event_types
    assert "agent_message" in event_types
    assert event_types[-1] == "session_end"
    assert transport.flushed is True

    tool_call = next(event for event in transport.events if event["type"] == "tool_call")
    tool_result = next(event for event in transport.events if event["type"] == "tool_result")
    assert tool_result["payload"]["call_id"] == tool_call["payload"]["call_id"]


def test_readme_decorator_example_emits_expected_events():
    transport = RecordingTransport()

    @pt.tool
    def search_calendar(day: str) -> list[str]:
        return ["Tuesday 2pm", "Tuesday 3pm"]

    @pt.traced("choose-slot")
    def choose_slot(slots: list[str]) -> str:
        return "Wednesday 2pm"

    @pt.observe(
        agent="calendar-agent",
        user_goal="Book Tuesday at 2pm",
        transport=transport,
    )
    def run_agent(goal: str) -> str:
        pt.current().user_message(goal)
        slots = search_calendar("Tuesday")
        selected = choose_slot(slots)
        pt.current().agent_message(f"Booked {selected}")
        pt.current().goal_check(
            False,
            mismatches=["selected Wednesday, not Tuesday"],
        )
        return selected

    assert run_agent("Book Tuesday at 2pm") == "Wednesday 2pm"

    event_types = [event["type"] for event in transport.events]
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "agent_message" in event_types
    assert "goal_check" in event_types
    assert event_types[-1] == "session_end"

    assert any(
        event["type"] == "tool_call"
        and event["payload"]["tool_name"] == "search_calendar"
        for event in transport.events
    )
    assert any(
        event["type"] == "goal_check" and event["payload"]["passed"] is False
        for event in transport.events
    )


def test_tool_is_noop_without_session():
    @pt.tool
    def add(a, b):
        return a + b

    assert add(1, 2) == 3


def test_trace_start_context_manager_records_goal_check():
    transport = RecordingTransport()

    with pt.trace.start(agent="demo-agent", user_goal="verify", transport=transport) as session:
        session.goal_check(False, ["wrong value"])

    assert any(event["type"] == "goal_check" for event in transport.events)


def test_resolve_transport_defaults_to_local_spool(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMPTETHEUS_API_URL", raising=False)
    monkeypatch.delenv("PROMPTETHEUS_API_KEY", raising=False)
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "no-config.toml")
    config_module.reset_config()

    transport = resolve_transport(spool_dir=str(tmp_path))

    assert isinstance(transport, LocalSpoolTransport)
    assert transport.spool_dir == tmp_path
    config_module.reset_config()


def test_resolve_transport_uses_hosted_default_when_api_key_present(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMPTETHEUS_API_URL", raising=False)
    monkeypatch.delenv("PROMPTETHEUS_HTTP_TIMEOUT", raising=False)
    monkeypatch.setenv("PROMPTETHEUS_API_KEY", "pt_live_test")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "no-config.toml")
    config_module.reset_config()

    transport = resolve_transport(spool_dir=str(tmp_path))

    assert isinstance(transport, DurableHTTPTransport)
    assert transport.endpoint == f"{DEFAULT_API_URL}/"
    assert transport.api_key == "pt_live_test"
    assert transport.timeout == DEFAULT_HTTP_TIMEOUT
    config_module.reset_config()


def test_resolve_transport_uses_env_http_timeout(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMPTETHEUS_API_URL", raising=False)
    monkeypatch.setenv("PROMPTETHEUS_API_KEY", "pt_live_test")
    monkeypatch.setenv("PROMPTETHEUS_HTTP_TIMEOUT", "42")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "no-config.toml")
    config_module.reset_config()

    transport = resolve_transport(spool_dir=str(tmp_path))

    assert isinstance(transport, DurableHTTPTransport)
    assert transport.timeout == 42.0
    config_module.reset_config()


def test_resolve_transport_uses_http_when_endpoint_present():
    transport = resolve_transport(endpoint="http://localhost:4318", api_key="pt_key")

    assert isinstance(transport, DurableHTTPTransport)
    assert transport.endpoint == "http://localhost:4318/"
    assert transport.api_key == "pt_key"


def test_resolve_transport_http_requires_api_key():
    with pytest.raises(ValueError, match="api_key"):
        resolve_transport("http", endpoint="http://localhost:4318")


def test_resolve_transport_memory_shortcut():
    assert isinstance(resolve_transport("memory"), InMemoryTransport)


def test_session_id_is_ulid():
    transport = RecordingTransport()
    with pt.trace.start(agent="demo-agent", user_goal="verify", transport=transport) as session:
        sid = session.session_id
    assert sid.startswith("0") or sid[0].isalnum()
    assert len(sid) == 26
    assert sid.isupper() or sid.isalnum()


def test_screenshot_uploads_artifact_identity():
    transport = RecordingTransport()

    class ArtifactTransport(RecordingTransport):
        def upload_artifact(self, session_id, *, body, content_type, filename=None, artifact_type=None):
            return {
                "artifact_id": "artifact_99",
                "storage_path": f"artifacts/ws/{session_id}/artifact_99/{filename}",
            }

    transport = ArtifactTransport()
    with pt.trace.start(agent="demo-agent", user_goal="shot", transport=transport) as session:
        session.screenshot(b"\x89PNG\r\n", metadata={"step": 1})

    shot = next(e for e in transport.events if e["type"] == "screenshot")
    assert shot["payload"]["artifact_id"] == "artifact_99"
    assert "storage_path" in shot["payload"]
