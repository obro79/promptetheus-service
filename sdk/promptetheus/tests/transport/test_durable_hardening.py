"""Tests for durable-transport hardening: gzip bodies + jittered backoff.

These cover the opt-in behaviors added on top of the existing durable transport:

- request bodies at or above compress_min_bytes are gzip-compressed and carry
  Content-Encoding: gzip; smaller bodies stay uncompressed,
- the server still receives the same JSON after gunzip (round-trip),
- compression can be disabled (compress_min_bytes=0),
- the retry backoff draws a delay from [0, window) using full jitter, with the
  window following the capped exponential schedule.

The network is faked the same way as test_durable.py: we patch
promptetheus.transport.http.urlopen, which the durable POST path references so
the patch intercepts it.
"""

from __future__ import annotations

import gzip
import json
import threading
import time

import pytest

from promptetheus.transport import DurableHTTPTransport
from promptetheus.transport import durable as durable_mod


def event(session_id: str = "sess_123", seq: int = 1, payload: dict | None = None) -> dict:
    return {
        "type": "browser_action",
        "session_id": session_id,
        "timestamp": "2026-06-12T12:34:56.000Z",
        "seq": seq,
        "idempotency_key": f"{session_id}:nonce:{seq}",
        "payload": payload or {"action": "click"},
    }


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


class RecordingPoster:
    """Records each request's raw body and headers; always returns 200 OK."""

    def __init__(self):
        self.requests: list[tuple[str, bytes, dict]] = []
        self._lock = threading.Lock()
        self.delivered = threading.Event()

    def __call__(self, request, timeout=None):
        data = request.data or b""
        headers = dict(request.headers)
        encoding = headers.get("Content-encoding") or headers.get("Content-Encoding")
        if encoding == "gzip":
            data = gzip.decompress(data)
        payload = json.loads(data.decode("utf-8")) if data else {}
        with self._lock:
            # request.headers normalizes header names to capitalized form.
            self.requests.append((request.full_url, request.data, headers))
            self.delivered.set()
        return _FakeResponse(
            json.dumps(
                {"accepted": len(payload.get("events", [])), "rejected": []}
            ).encode("utf-8")
        )

    def wait(self, timeout: float = 5.0) -> bool:
        return self.delivered.wait(timeout)


@pytest.fixture
def poster(monkeypatch):
    rec = RecordingPoster()
    monkeypatch.setattr("promptetheus.transport.http.urlopen", rec)
    return rec


def make_transport(tmp_path, **kwargs):
    defaults = dict(
        spool_dir=str(tmp_path / "spool"),
        batch_size=50,
        flush_interval=0.01,
        max_retries=3,
        timeout=1.0,
    )
    defaults.update(kwargs)
    transport = DurableHTTPTransport("http://example.test", api_key="pt_key", **defaults)
    transport._sleep_backoff = lambda attempt: None  # type: ignore[assignment]
    return transport


def _decode_body(data: bytes, headers: dict) -> dict:
    """Gunzip if Content-Encoding header says so, then JSON-decode."""

    encoding = headers.get("Content-encoding") or headers.get("Content-Encoding")
    if encoding == "gzip":
        data = gzip.decompress(data)
    return json.loads(data.decode("utf-8"))


# -- gzip compression -------------------------------------------------------


def test_large_body_is_gzip_compressed_and_round_trips(poster, tmp_path):
    # A low threshold so a single fat event clears it deterministically.
    transport = make_transport(tmp_path, compress_min_bytes=64)
    big_payload = {"action": "click", "blob": "x" * 4096}
    try:
        transport.send_event(event("sess_big", 1, payload=big_payload))
        transport.flush(timeout=5.0)
        assert poster.wait(timeout=5.0)

        url, data, headers = poster.requests[-1]
        assert headers.get("Content-encoding") == "gzip"
        # The compressed body is smaller than the equivalent raw JSON.
        raw = json.dumps({"events": [event("sess_big", 1, payload=big_payload)]}).encode("utf-8")
        assert len(data) < len(raw)
        # Round-trip: the server still sees the exact same JSON after gunzip.
        decoded = _decode_body(data, headers)
        assert decoded["events"][0]["payload"] == big_payload
    finally:
        transport.close()


def test_small_body_is_not_compressed(poster, tmp_path):
    transport = make_transport(tmp_path, compress_min_bytes=4096)
    try:
        transport.send_event(event("sess_small", 1))
        transport.flush(timeout=5.0)
        assert poster.wait(timeout=5.0)

        url, data, headers = poster.requests[-1]
        assert "Content-encoding" not in headers
        # Body is plain JSON, parseable without gunzip.
        decoded = json.loads(data.decode("utf-8"))
        assert decoded["events"][0]["seq"] == 1
    finally:
        transport.close()


def test_compression_can_be_disabled(poster, tmp_path):
    # compress_min_bytes=0 disables compression regardless of body size.
    transport = make_transport(tmp_path, compress_min_bytes=0)
    big_payload = {"blob": "y" * 8192}
    try:
        transport.send_event(event("sess_off", 1, payload=big_payload))
        transport.flush(timeout=5.0)
        assert poster.wait(timeout=5.0)

        url, data, headers = poster.requests[-1]
        assert "Content-encoding" not in headers
        decoded = json.loads(data.decode("utf-8"))
        assert decoded["events"][0]["payload"] == big_payload
    finally:
        transport.close()


# -- jittered backoff -------------------------------------------------------


def test_backoff_delay_is_within_jitter_window(tmp_path):
    transport = make_transport(tmp_path)
    try:
        # For each attempt the window is base*2**attempt capped at the ceiling,
        # and the delay is drawn from [0, window). Sample repeatedly to confirm
        # the bound holds and at least one draw is strictly inside the window
        # (i.e. jitter is actually applied, not a constant full-window wait).
        for attempt in range(6):
            window = min(durable_mod._BACKOFF_BASE * (2**attempt), durable_mod._BACKOFF_CAP)
            samples = [transport._backoff_delay(attempt) for _ in range(200)]
            assert all(0.0 <= s < window for s in samples)
            assert any(s < window * 0.95 for s in samples)
    finally:
        transport.close()


def test_backoff_window_is_capped(tmp_path):
    transport = make_transport(tmp_path)
    try:
        # A very large attempt must not exceed the cap.
        for _ in range(100):
            assert transport._backoff_delay(50) < durable_mod._BACKOFF_CAP
    finally:
        transport.close()


def test_backoff_is_deterministic_under_seed(tmp_path):
    # Full jitter uses the stdlib random module; seeding makes it reproducible.
    transport = make_transport(tmp_path)
    try:
        import random

        random.seed(1234)
        first = [transport._backoff_delay(a) for a in range(5)]
        random.seed(1234)
        second = [transport._backoff_delay(a) for a in range(5)]
        assert first == second
    finally:
        transport.close()
