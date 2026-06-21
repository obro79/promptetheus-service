"""MCP trace-event tool tests that do not require the optional MCP SDK."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server import create_app  # noqa: E402
from promptetheus.server.mcp import server as tools  # noqa: E402
from promptetheus.server.mcp.client import PromptetheusClient  # noqa: E402
from promptetheus.server.store import InMemoryStore  # noqa: E402

KEY_AUTH = {"Authorization": "Bearer pt_dev_key"}

SECRET_TOKEN = "sk-trace-tool-secret-1234567890"
SECRET_PASSWORD = "trace-tool-password"


def test_get_trace_events_redacts_raw_payloads() -> None:
    store = InMemoryStore()
    app = create_app(store=store)
    trace_id = "trace_mcp_events"

    with testclient.TestClient(app) as seed:
        assert (
            seed.post(
                "/api/traces",
                json={"user_goal": "Book Tuesday", "id": trace_id},
                headers=KEY_AUTH,
            ).status_code
            == 201
        )
        response = seed.post(
            f"/api/traces/{trace_id}/events",
            json={
                "events": [
                    {
                        "type": "user_message",
                        "session_id": trace_id,
                        "timestamp": "2026-01-01T00:00:00Z",
                        "seq": 1,
                        "idempotency_key": "event_1",
                        "payload": {
                            "content": "Book Tuesday",
                            "authorization": f"Bearer {SECRET_TOKEN}",
                        },
                    },
                    {
                        "type": "browser_action",
                        "session_id": trace_id,
                        "timestamp": "2026-01-01T00:00:01Z",
                        "seq": 2,
                        "idempotency_key": "event_2",
                        "payload": {
                            "action": "click",
                            "target": "#wednesday",
                            "password": SECRET_PASSWORD,
                        },
                    },
                ]
            },
            headers=KEY_AUTH,
        )
        assert response.status_code == 200

    raw = json.dumps(store.get_events(trace_id))
    assert SECRET_TOKEN in raw
    assert SECRET_PASSWORD in raw

    client = PromptetheusClient(
        api_key="pt_dev_key", http_client=testclient.TestClient(app)
    )
    try:
        timeline = tools.get_trace_events(client, trace_id)
    finally:
        client.close()

    assert [event["seq"] for event in timeline["events"]] == [1, 2]
    serialized = json.dumps(timeline)
    assert SECRET_TOKEN not in serialized
    assert SECRET_PASSWORD not in serialized
    assert "[REDACTED]" in serialized
