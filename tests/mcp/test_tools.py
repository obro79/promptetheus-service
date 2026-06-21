"""Tool tests for the incident-context MCP server.

Each tool is driven against a real FastAPI app wired to a seeded InMemoryStore
through an in-process httpx ASGITransport — the same path the stdio server uses
in production, minus the transport. The tests assert the read tools never expose
redacted secret fields and that link_pr_to_incident writes through the gateway
and records an audit row.

Skipped cleanly when the optional ``mcp`` SDK is not installed.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("mcp")
fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")
pytest.importorskip("httpx")

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server import create_app  # noqa: E402
from promptetheus.server.mcp import build_server  # noqa: E402
from promptetheus.server.mcp import server as tools  # noqa: E402
from promptetheus.server.mcp.client import PromptetheusClient  # noqa: E402
from promptetheus.server.store import InMemoryStore  # noqa: E402

KEY_AUTH = {"Authorization": "Bearer pt_dev_key"}
CONSOLE_AUTH = {"Authorization": "Bearer pt_console_token"}

SECRET_TOKEN = "sk-supersecret-DEADBEEF"
SECRET_PASSWORD = "hunter2-not-leaked"


def _failing_events(session_id: str) -> list[dict]:
    """An AcmeMeet-style failing booking with a secret planted in payloads.

    The secret fields (authorization/password) must be redacted out of the
    bundle before it leaves the server, so the MCP read tools never see them.
    """

    def event(seq: int, etype: str, payload: dict, **extra: object) -> dict:
        evt = {
            "type": etype,
            "session_id": session_id,
            "timestamp": f"2026-01-01T00:00:0{seq}Z",
            "seq": seq,
            "idempotency_key": f"{session_id}-{seq}",
            "payload": payload,
        }
        evt.update(extra)
        return evt

    return [
        event(
            1,
            "user_message",
            {
                "content": "Book a meeting room for Tuesday",
                "authorization": f"Bearer {SECRET_TOKEN}",
            },
        ),
        event(
            2,
            "browser_action",
            {"action": "click", "target": "#wednesday", "password": SECRET_PASSWORD},
        ),
        event(
            3,
            "dom_snapshot",
            {
                "selected_values": {"day": "Wednesday"},
                "warnings": ["Room unavailable"],
            },
        ),
        event(4, "browser_action", {"action": "submit", "target": "#confirm"}),
        event(5, "agent_message", {"content": "Done! Successfully booked."}),
        event(6, "goal_check", {"passed": False, "mismatches": ["wrong day"]}),
        event(7, "session_end", {"status": "success"}),
    ]


@pytest.fixture()
def wired() -> Iterator[tuple[PromptetheusClient, InMemoryStore, str]]:
    """Seed an app+store with one incident and return (client, store, incident_id)."""

    store = InMemoryStore()
    app = create_app(store=store)

    with testclient.TestClient(app) as seed:
        seed.post("/api/traces", json={"user_goal": "Book Tuesday", "id": "trace_1"}, headers=KEY_AUTH)
        seed.post(
            "/api/traces/trace_1/events",
            json={"events": _failing_events("trace_1")},
            headers=KEY_AUTH,
        )
        seed.post(
            "/api/traces/trace_1/artifacts",
            json={
                "content_type": "video/webm",
                "filename": "replay.webm",
                "size_bytes": 4096,
                "artifact_type": "replay",
            },
            headers=KEY_AUTH,
        )
        incidents = seed.post(
            "/api/traces/trace_1/analyze", headers=CONSOLE_AUTH
        ).json()["incidents"]
        incident_id = incidents[0]["id"]

    # A Starlette TestClient is a sync httpx client wired to the in-process app;
    # injecting it drives every tool over the real request path without a server.
    http_client = testclient.TestClient(app)
    client = PromptetheusClient(api_key="pt_dev_key", http_client=http_client)
    try:
        yield client, store, incident_id
    finally:
        client.close()


def test_get_incident_tool(wired: tuple[PromptetheusClient, InMemoryStore, str]) -> None:
    client, _store, incident_id = wired
    incident = tools.get_incident(client, incident_id)
    assert incident["id"] == incident_id
    assert incident["label"] == "browser_goal_mismatch"


def test_failure_evidence_redacts_secrets(
    wired: tuple[PromptetheusClient, InMemoryStore, str],
) -> None:
    client, store, incident_id = wired

    # The raw secrets are genuinely stored on the events...
    raw = json.dumps(store.get_events("trace_1"))
    assert SECRET_TOKEN in raw
    assert SECRET_PASSWORD in raw

    evidence = tools.get_failure_evidence(client, incident_id)
    assert "browser_goal_mismatch" in evidence["labels"]
    assert evidence["evidence"]
    assert evidence["events"]

    # ...but they are redacted out of everything the tool returns.
    serialized = json.dumps(evidence)
    assert SECRET_TOKEN not in serialized
    assert SECRET_PASSWORD not in serialized
    assert "[REDACTED]" in serialized


def test_trace_events_tool_redacts_payloads(
    wired: tuple[PromptetheusClient, InMemoryStore, str],
) -> None:
    client, store, _incident_id = wired

    raw = json.dumps(store.get_events("trace_1"))
    assert SECRET_TOKEN in raw
    assert SECRET_PASSWORD in raw

    timeline = tools.get_trace_events(client, "trace_1")
    events = timeline["events"]
    assert timeline["trace_id"] == "trace_1"
    assert [event["seq"] for event in events] == [1, 2, 3, 4, 5, 6, 7]
    assert [event["type"] for event in events][:2] == [
        "user_message",
        "browser_action",
    ]

    serialized = json.dumps(timeline)
    assert SECRET_TOKEN not in serialized
    assert SECRET_PASSWORD not in serialized
    assert "[REDACTED]" in serialized


def test_replay_timeline_tool(
    wired: tuple[PromptetheusClient, InMemoryStore, str],
) -> None:
    client, _store, incident_id = wired
    timeline = tools.get_replay_timeline(client, incident_id)
    assert timeline["signed_url"].startswith("https://artifacts.local/signed/")
    assert "1" in timeline["event_time_map"]
    assert SECRET_TOKEN not in json.dumps(timeline)


def test_regression_case_tool(
    wired: tuple[PromptetheusClient, InMemoryStore, str],
) -> None:
    client, store, incident_id = wired
    # No run yet.
    assert tools.get_regression_case(client, incident_id)["regression_case"] is None

    # Persist a regression run on the shared store; the tool surfaces the latest.
    store_run = store.add_regression_run(
        {
            "incident_id": incident_id,
            "workspace_id": "ws_dev",
            "before_pass": 0,
            "before_fail": 1,
            "after_pass": 1,
            "after_fail": 0,
            "fallback": True,
        }
    )
    case = tools.get_regression_case(client, incident_id)["regression_case"]
    assert case is not None
    assert case["id"] == store_run["id"]


def test_search_similar_incidents_tool(
    wired: tuple[PromptetheusClient, InMemoryStore, str],
) -> None:
    client, _store, _incident_id = wired
    result = tools.search_similar_incidents(client, "browser")
    labels = {incident["label"] for incident in result["incidents"]}
    assert "browser_goal_mismatch" in labels
    assert tools.search_similar_incidents(client, "zzz")["incidents"] == []


def test_connected_repo_tool(
    wired: tuple[PromptetheusClient, InMemoryStore, str],
) -> None:
    client, _store, _incident_id = wired
    repo = tools.get_connected_repo(client, "proj_dev")
    assert repo["project_id"] == "proj_dev"
    assert repo["allowed_paths"] == ["agents/"]
    assert repo["stub"] is True


def test_link_pr_to_incident_writes_through_and_audits(
    wired: tuple[PromptetheusClient, InMemoryStore, str],
) -> None:
    client, store, incident_id = wired
    pr_url = "https://github.com/acme/repo/pull/7"

    console_client = PromptetheusClient(
        console_token="pt_console_token",
        http_client=testclient.TestClient(create_app(store=store)),
    )
    result = tools.link_pr_to_incident(console_client, incident_id, pr_url)
    assert result["pr_url"] == pr_url

    # The write landed on the canonical store...
    assert store.get_incident(incident_id)["pr_url"] == pr_url
    # ...and produced an audit row.
    audit = store.list_audit(workspace_id="ws_dev")
    pr_audits = [row for row in audit if row.get("action") == "incident_pr_link"]
    assert pr_audits and pr_audits[-1]["incident_id"] == incident_id


def test_build_server_registers_tools() -> None:
    store = InMemoryStore()
    app = create_app(store=store)
    client = PromptetheusClient(
        console_token="pt_console_token", http_client=testclient.TestClient(app)
    )
    try:
        server = build_server(client)
        assert server.name == tools.SERVER_NAME
    finally:
        client.close()
