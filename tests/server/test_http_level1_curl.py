"""Level-1 HTTP curl contract smoke tests (P10.4–P10.7)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server import create_app  # noqa: E402

KEY_AUTH = {"Authorization": "Bearer pt_dev_key"}
CONSOLE_AUTH = {"Authorization": "Bearer pt_console_token"}


@pytest.fixture()
def client() -> testclient.TestClient:
    return testclient.TestClient(create_app())


def test_create_trace_requires_auth(client: testclient.TestClient) -> None:
    response = client.post("/api/traces", json={"user_goal": "x"})
    assert response.status_code == 401


def test_create_trace_with_api_key(client: testclient.TestClient) -> None:
    response = client.post(
        "/api/traces",
        json={"user_goal": "Book Tuesday", "id": "trace_curl_1"},
        headers=KEY_AUTH,
    )
    assert response.status_code == 201
    assert response.json()["trace"]["id"] == "trace_curl_1"


def test_append_events_with_api_key(client: testclient.TestClient) -> None:
    client.post(
        "/api/traces",
        json={"user_goal": "g", "id": "trace_curl_2"},
        headers=KEY_AUTH,
    )
    response = client.post(
        "/api/traces/trace_curl_2/events",
        json={
            "events": [
                {
                    "type": "user_message",
                    "session_id": "trace_curl_2",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "seq": 0,
                    "idempotency_key": "trace_curl_2:n:0",
                    "payload": {"content": "hi"},
                }
            ]
        },
        headers=KEY_AUTH,
    )
    assert response.status_code == 200
    assert response.json()["accepted"] == 1
