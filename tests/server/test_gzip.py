"""The server must decode gzip-encoded request bodies.

The SDK's durable transport gzip-compresses large batches and sets
Content-Encoding: gzip. Starlette does not auto-decompress request bodies, so the
write gateway decodes them itself. These tests pin that behaviour end to end.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server import create_app  # noqa: E402

KEY_AUTH = {"Authorization": "Bearer pt_dev_key"}


def _event(seq: int) -> dict:
    return {
        "type": "agent_message",
        "session_id": "trace_gz",
        "timestamp": "2026-01-01T00:00:00Z",
        "seq": seq,
        "idempotency_key": f"trace_gz:n:{seq}",
        "payload": {"content": "hello"},
    }


def _client() -> "testclient.TestClient":
    client = testclient.TestClient(create_app())
    client.post("/api/traces", json={"id": "trace_gz", "user_goal": "g"}, headers=KEY_AUTH)
    return client


def test_gzip_encoded_events_are_accepted() -> None:
    client = _client()
    body = json.dumps({"events": [_event(1), _event(2)]}).encode("utf-8")
    gz = gzip.compress(body)

    response = client.post(
        "/api/traces/trace_gz/events",
        content=gz,
        headers={**KEY_AUTH, "Content-Encoding": "gzip", "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 2
    # The decoded events are actually stored and ordered.
    events = client.get("/api/traces/trace_gz/events", headers={"Authorization": "Bearer pt_console_token"}).json()["events"]
    assert [e["seq"] for e in events] == [1, 2]


def test_malformed_gzip_body_is_400() -> None:
    client = _client()
    response = client.post(
        "/api/traces/trace_gz/events",
        content=b"not actually gzip",
        headers={**KEY_AUTH, "Content-Encoding": "gzip", "Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_uncompressed_still_works() -> None:
    client = _client()
    response = client.post(
        "/api/traces/trace_gz/events",
        json={"events": [_event(1)]},
        headers=KEY_AUTH,
    )
    assert response.status_code == 200
    assert response.json()["accepted"] == 1
