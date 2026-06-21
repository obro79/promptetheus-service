"""Circuit breaker + stats() for the durable transport."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.transport import http as http_module  # noqa: E402
from promptetheus.transport.durable import DurableHTTPTransport, _CircuitBreaker  # noqa: E402


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_circuit_breaker_opens_and_half_opens():
    clock = _Clock()
    cb = _CircuitBreaker(failure_threshold=2, reset_seconds=10.0, clock=clock)
    assert cb.allow() is True and cb.state() == "closed"
    cb.record_failure()
    assert cb.state() == "closed"  # one failure, below threshold
    cb.record_failure()
    assert cb.state() == "open" and cb.allow() is False  # tripped
    clock.t = 9.0
    assert cb.allow() is False  # still in cooldown
    clock.t = 10.0
    assert cb.allow() is True and cb.state() == "half_open"  # probe allowed
    cb.record_success()
    assert cb.state() == "closed" and cb.allow() is True


def test_circuit_breaker_failed_probe_reopens():
    clock = _Clock()
    cb = _CircuitBreaker(failure_threshold=1, reset_seconds=5.0, clock=clock)
    cb.record_failure()
    assert cb.state() == "open"
    clock.t = 5.0
    assert cb.allow() is True  # half-open probe
    cb.record_failure()  # probe failed
    clock.t = 6.0
    assert cb.allow() is False  # reopened, cooldown restarted


class _Resp:
    def __init__(self, body=b"{}"):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def test_stats_counts_deliveries(monkeypatch):
    sent = []

    def ok_urlopen(request, timeout):
        sent.append(request.full_url)
        payload = json.loads(request.data.decode("utf-8")) if request.data else {}
        body = json.dumps(
            {"accepted": len(payload.get("events", [])), "rejected": []}
        ).encode("utf-8")
        return _Resp(body)

    monkeypatch.setattr(http_module, "urlopen", ok_urlopen)
    t = DurableHTTPTransport("http://x.test", flush_interval=0.01)
    try:
        t.send_batch([
            {"type": "agent_message", "session_id": "s", "seq": 0, "idempotency_key": "s:n:0", "payload": {}},
            {"type": "agent_message", "session_id": "s", "seq": 1, "idempotency_key": "s:n:1", "payload": {}},
        ])
        t.flush()
    finally:
        t.close()
    stats = t.stats()
    assert stats["enqueued"] == 2
    assert stats["delivered_batches"] >= 1
    assert stats["delivered_events"] == 2
    assert stats["circuit_state"] == "closed"
    assert "queue_depth" in stats


def test_stats_counts_spool_on_failure(monkeypatch):
    from urllib.error import URLError

    def failing_urlopen(request, timeout):
        raise URLError("down")

    monkeypatch.setattr(http_module, "urlopen", failing_urlopen)
    t = DurableHTTPTransport(
        "http://x.test", flush_interval=0.01, max_retries=0, circuit_failure_threshold=1
    )
    try:
        t.send_batch([
            {"type": "agent_message", "session_id": "s", "seq": 0, "idempotency_key": "s:n:0", "payload": {}},
        ])
        t.flush()
    finally:
        t.close()
    stats = t.stats()
    assert stats["spooled_events"] >= 1
    # one delivery failure with threshold 1 trips the breaker
    assert stats["circuit_state"] in ("open", "half_open")
