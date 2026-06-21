from __future__ import annotations

import json

import pytest

from promptetheus import config as config_module
from promptetheus.transport import BaseTransport, InMemoryTransport, LocalSpoolTransport
from promptetheus.transport.http import HTTPTransport


def event(session_id: str = "sess_123", seq: int = 1) -> dict:
    return {
        "type": "browser_action",
        "session_id": session_id,
        "timestamp": "2026-06-12T12:34:56.000Z",
        "seq": seq,
        "idempotency_key": f"{session_id}:nonce:{seq}",
        "payload": {"action": "click"},
    }


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_in_memory_transport_records_events_in_order():
    transport = InMemoryTransport()

    transport.send_event(event(seq=1))
    transport.send_batch([event(seq=2), event(seq=3)])
    transport.flush()

    assert [record["seq"] for record in transport.events] == [1, 2, 3]
    assert transport.flush_count == 1


def test_close_flushes_and_rejects_later_sends():
    transport = InMemoryTransport()

    transport.send_event(event())
    transport.close()

    assert transport.closed is True
    assert transport.flush_count == 1
    with pytest.raises(RuntimeError):
        transport.send_event(event(seq=2))


def test_base_transport_send_batch_delegates_to_send_event():
    class RecordingTransport(BaseTransport):
        def __init__(self):
            super().__init__()
            self.seen = []

        def send_event(self, item):
            self._ensure_open()
            self.seen.append(item["seq"])

    transport = RecordingTransport()
    transport.send_batch([event(seq=1), event(seq=2)])

    assert transport.seen == [1, 2]


def test_local_spool_transport_writes_jsonl_on_flush(tmp_path):
    transport = LocalSpoolTransport(tmp_path)

    transport.send_event(event(seq=1))
    transport.send_event(event(seq=2))

    assert list(tmp_path.iterdir()) == []
    assert transport.pending_count == 2

    transport.flush()

    spool_file = tmp_path / "sess_123.jsonl"
    assert read_jsonl(spool_file) == [event(seq=1), event(seq=2)]
    assert transport.pending_count == 0


def test_local_spool_transport_groups_by_session_and_appends(tmp_path):
    transport = LocalSpoolTransport(tmp_path)

    transport.send_batch([event("sess/a", 1), event("sess_b", 1), event("sess/a", 2)])
    transport.flush()
    transport.send_event(event("sess/a", 3))
    transport.flush()

    assert read_jsonl(tmp_path / "sess_a.jsonl") == [
        event("sess/a", 1),
        event("sess/a", 2),
        event("sess/a", 3),
    ]
    assert read_jsonl(tmp_path / "sess_b.jsonl") == [event("sess_b", 1)]


def test_local_spool_transport_noop_flush_does_not_create_directory(tmp_path):
    spool_dir = tmp_path / "spool"
    transport = LocalSpoolTransport(spool_dir)

    transport.flush()

    assert not spool_dir.exists()


def test_http_transport_requires_endpoint():
    transport = HTTPTransport("http://example.test/api")

    assert transport.endpoint == "http://example.test/api/"


def test_http_transport_uses_env_timeout_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMPTETHEUS_HTTP_TIMEOUT", "22")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "no-config.toml")
    config_module.reset_config()

    transport = HTTPTransport("http://example.test/api")

    assert transport.timeout == 22.0
    config_module.reset_config()


def test_http_transport_explicit_timeout_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMPTETHEUS_HTTP_TIMEOUT", "22")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "no-config.toml")
    config_module.reset_config()

    transport = HTTPTransport("http://example.test/api", timeout=1.5)

    assert transport.timeout == 1.5
    config_module.reset_config()


def test_http_transport_groups_batches_by_session(monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, request.data, timeout))
        return Response()

    monkeypatch.setattr("promptetheus.transport.http.urlopen", fake_urlopen)
    transport = HTTPTransport("http://example.test", timeout=1.5)

    transport.send_batch([event("sess_a", 1), event("sess_b", 1), event("sess_a", 2)])

    assert [request[0] for request in requests] == [
        "http://example.test/api/traces/sess_a/events",
        "http://example.test/api/traces/sess_b/events",
    ]


def test_http_transport_uploads_artifact_bytes(monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "artifact": {
                        "artifact_id": "artifact_1",
                        "storage_path": "artifacts/ws/sess_art/artifact_1/step.png",
                    }
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, request.data, dict(request.header_items())))
        return Response()

    monkeypatch.setattr("promptetheus.transport.http.urlopen", fake_urlopen)
    transport = HTTPTransport("http://example.test", api_key="pt_dev_key", timeout=1.5)

    artifact = transport.upload_artifact(
        "sess_art",
        body=b"PNG",
        content_type="image/png",
        filename="step.png",
        artifact_type="screenshot",
    )

    assert artifact == {
        "artifact_id": "artifact_1",
        "storage_path": "artifacts/ws/sess_art/artifact_1/step.png",
    }
    assert requests[0][0] == "http://example.test/api/traces/sess_art/artifacts"
    assert requests[0][1] == b"PNG"
    assert requests[0][2]["Content-type"] == "image/png"
    assert requests[0][2]["X-promptetheus-filename"] == "step.png"
    assert requests[0][2]["X-promptetheus-artifact-type"] == "screenshot"
    assert requests[0][2]["Authorization"] == "Bearer pt_dev_key"
