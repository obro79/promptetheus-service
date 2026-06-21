"""Tests for the durable HTTP transport (P8).

The network is always faked: we patch promptetheus.transport.http.urlopen so
no real server is contacted. The fake lets each test script a sequence of
responses (success bodies, HTTP error statuses, or raised network errors) per
/api/traces/{id}/events POST, and records every request it sees.

Determinism: tests use batch_size=50 (so a session's events go out in one
POST), flush_interval near zero (so the flusher parks briefly), and a
no-op backoff (patched per-instance) so retries do not actually sleep. We wait
on delivery via the recording fake's threading.Event, never via fixed
sleeps.
"""

from __future__ import annotations

import json
import threading
import time
from urllib.error import HTTPError, URLError

import pytest

from promptetheus import config as config_module
from promptetheus.transport import DurableHTTPTransport


# -- envelope helper --------------------------------------------------------


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


def read_spool_records(spool_dir):
    records = []
    if not spool_dir.exists():
        return records
    for path in spool_dir.glob("*.jsonl"):
        try:
            records.extend(read_jsonl(path))
        except FileNotFoundError:
            # The durable transport may rotate/replay a spool file between glob
            # and read while its background flusher is active. Treat that as an
            # empty poll and let the caller's wait loop retry.
            continue
    return records


# -- fake network -----------------------------------------------------------


class _FakeResponse:
    """Context-manager response whose read() returns a JSON body."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


class FakePoster:
    """Programmable stand-in for urllib.request.urlopen.

    Each call records (url, parsed_payload) and then performs the next
    scripted action. Actions are callables that either return a _FakeResponse
    or raise. The default action (once the script is exhausted) is a 200 with an
    empty-accept body, so "...then succeeds" cases just append nothing.
    """

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._actions: list = []
        self._lock = threading.Lock()
        self.delivered = threading.Event()
        # Number of successful (200) deliveries observed; used to wait reliably.
        self.success_count = 0
        self._default = self._ok_action()

    # -- scripting helpers --------------------------------------------------

    @staticmethod
    def _ok_action(body: dict | None = None):
        def action(url, payload):
            result = body
            if result is None:
                result = {"accepted": len(payload.get("events", [])), "rejected": []}
            return _FakeResponse(json.dumps(result).encode("utf-8"))

        return action

    @staticmethod
    def _http_error_action(code: int):
        def action(url, payload):
            raise HTTPError(url, code, f"status {code}", hdrs=None, fp=None)

        return action

    @staticmethod
    def _urlerror_action():
        def action(url, payload):
            raise URLError("connection refused")

        return action

    def ok(self, body: dict | None = None):
        self._actions.append(self._ok_action(body))
        return self

    def http_error(self, code: int):
        self._actions.append(self._http_error_action(code))
        return self

    def network_error(self):
        self._actions.append(self._urlerror_action())
        return self

    def set_default(self, action):
        self._default = action
        return self

    # -- the urlopen replacement -------------------------------------------

    def __call__(self, request, timeout=None):
        url = request.full_url
        payload = json.loads(request.data.decode("utf-8")) if request.data else {}
        with self._lock:
            self.calls.append((url, payload))
            action = self._actions.pop(0) if self._actions else self._default
        try:
            response = action(url, payload)
        except Exception:
            raise
        else:
            with self._lock:
                self.success_count += 1
                self.delivered.set()
            return response

    # -- assertions helpers -------------------------------------------------

    def wait_success(self, count: int = 1, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self.success_count >= count:
                    return True
            time.sleep(0.005)
        return False

    @property
    def event_calls(self) -> list[tuple[str, dict]]:
        return [c for c in self.calls if "/events" in c[0]]


@pytest.fixture
def fake(monkeypatch):
    poster = FakePoster()
    monkeypatch.setattr("promptetheus.transport.http.urlopen", poster)
    return poster


def make_transport(fake, tmp_path, **kwargs):
    """Build a durable transport with fast, deterministic defaults.

    Backoff is replaced with a no-op so retry tests never actually sleep.
    """

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


# -- basic surface ----------------------------------------------------------


def test_exposes_endpoint_and_api_key(fake, tmp_path):
    transport = make_transport(fake, tmp_path)
    try:
        assert transport.endpoint == "http://example.test/"
        assert transport.api_key == "pt_key"
    finally:
        transport.close()


def test_uses_env_timeout_by_default(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPTETHEUS_HTTP_TIMEOUT", "24")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "no-config.toml")
    config_module.reset_config()
    transport = DurableHTTPTransport(
        "http://example.test",
        api_key="pt_key",
        spool_dir=str(tmp_path / "spool"),
    )
    try:
        assert transport.timeout == 24.0
        assert transport._poster.timeout == 24.0
    finally:
        transport.close()
        config_module.reset_config()


# -- happy path: non-blocking enqueue + background flush --------------------


def test_enqueue_is_nonblocking_and_background_flush_delivers_grouped(fake, tmp_path):
    transport = make_transport(fake, tmp_path)
    try:
        # Two sessions interleaved; batch_size is large so each session is one POST.
        transport.send_event(event("sess_a", 1))
        transport.send_event(event("sess_b", 1))
        transport.send_event(event("sess_a", 2))

        # flush() drains the queue and blocks until the flusher reports idle.
        transport.flush(timeout=5.0)

        assert fake.wait_success(count=2, timeout=5.0)

        # One POST per session, each carrying that session's events in order.
        urls = [url for url, _ in fake.event_calls]
        assert "http://example.test/api/traces/sess_a/events" in urls
        assert "http://example.test/api/traces/sess_b/events" in urls

        by_session = {}
        for url, payload in fake.event_calls:
            sid = url.rsplit("/api/traces/", 1)[1].split("/")[0]
            by_session.setdefault(sid, []).extend(e["seq"] for e in payload["events"])
        assert by_session["sess_a"] == [1, 2]
        assert by_session["sess_b"] == [1]
    finally:
        transport.close()


def test_spool_replay_cooldown_after_transient_failure(fake, tmp_path):
    fake.set_default(FakePoster._urlerror_action())
    transport = make_transport(fake, tmp_path)
    try:
        transport._spool("sess_123", [event("sess_123", 1)])

        transport._replay_spool(None)
        transport._replay_spool(None)

        assert len(fake.event_calls) == 1
    finally:
        transport.close()


# -- retry: transient failures then success --------------------------------


def test_retry_on_urlerror_then_succeeds(fake, tmp_path):
    # First attempt raises a network error, second attempt is a 200.
    fake.network_error().ok({"accepted": 1, "rejected": []})
    transport = make_transport(fake, tmp_path, max_retries=5)
    try:
        transport.send_event(event("sess_net", 1))
        transport.flush(timeout=5.0)

        assert fake.wait_success(count=1, timeout=5.0)
        # At least two attempts to the same session endpoint.
        urls = [url for url, _ in fake.event_calls]
        assert urls.count("http://example.test/api/traces/sess_net/events") >= 2
        # Nothing spooled and nothing dead-lettered; it eventually delivered.
        spool_dir = tmp_path / "spool"
        leftover = list(spool_dir.glob("*.jsonl")) if spool_dir.exists() else []
        assert leftover == []
    finally:
        transport.close()


def test_retry_on_500_then_succeeds(fake, tmp_path):
    fake.http_error(500).ok({"accepted": 1, "rejected": []})
    transport = make_transport(fake, tmp_path, max_retries=5)
    try:
        transport.send_event(event("sess_5xx", 7))
        transport.flush(timeout=5.0)

        assert fake.wait_success(count=1, timeout=5.0)
        delivered = [
            payload
            for url, payload in fake.event_calls
            if url.endswith("/sess_5xx/events")
        ][-1]
        assert [e["seq"] for e in delivered["events"]] == [7]
        spool_dir = tmp_path / "spool"
        assert not (spool_dir / "sess_5xx.jsonl").exists()
    finally:
        transport.close()


# -- dead-letter on permanent 4xx ------------------------------------------


def test_permanent_422_dead_letters_without_retry(fake, tmp_path):
    fake.http_error(422)  # only one scripted action; must not be retried
    transport = make_transport(fake, tmp_path, max_retries=5)
    try:
        transport.send_event(event("sess_bad", 3))
        transport.flush(timeout=5.0)

        # Wait for the dead-letter file to appear (delivery thread is async).
        dl_path = tmp_path / "spool" / "dead-letter" / "sess_bad.jsonl"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not dl_path.exists():
            time.sleep(0.005)

        assert dl_path.exists(), "permanent 4xx should dead-letter the batch"
        records = read_jsonl(dl_path)
        assert len(records) == 1
        assert records[0]["seq"] == 3
        assert records[0]["_reject_reason"] == "http_422"

        # Exactly one POST: 422 is not retried.
        assert len(fake.event_calls) == 1
        # Not spooled for replay.
        assert not (tmp_path / "spool" / "sess_bad.jsonl").exists()
    finally:
        transport.close()


# -- per-event reject from a 200 response -----------------------------------


def test_per_event_reject_dead_letters_only_rejected(fake, tmp_path):
    # 200 OK, but the server rejects the second event by idempotency_key.
    rejected_key = "sess_mix:nonce:2"
    fake.ok(
        {
            "accepted": 1,
            "rejected": [
                {"index": 1, "idempotency_key": rejected_key, "reason": "schema_invalid"}
            ],
        }
    )
    transport = make_transport(fake, tmp_path)
    try:
        transport.send_batch([event("sess_mix", 1), event("sess_mix", 2)])
        transport.flush(timeout=5.0)
        assert fake.wait_success(count=1, timeout=5.0)

        dl_path = tmp_path / "spool" / "dead-letter" / "sess_mix.jsonl"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not dl_path.exists():
            time.sleep(0.005)
        assert dl_path.exists()

        records = read_jsonl(dl_path)
        # Only the rejected event (seq 2) is dead-lettered.
        assert [r["seq"] for r in records] == [2]
        assert records[0]["idempotency_key"] == rejected_key
        assert records[0]["_reject_reason"] == "schema_invalid"

        # The accepted event (seq 1) is NOT dead-lettered and NOT spooled.
        assert not (tmp_path / "spool" / "sess_mix.jsonl").exists()
    finally:
        transport.close()


# -- spool on exhaustion, then replay on a later flush ----------------------


def test_spool_then_replay_after_network_restored(fake, tmp_path):
    # Keep the network DOWN by default so the just-spooled file is not replayed
    # (and deleted) by the flusher's opportunistic post-batch replay. We flip the
    # default to a 200 only once we've confirmed the spool file exists.
    fake.set_default(FakePoster._urlerror_action())
    transport = make_transport(fake, tmp_path, max_retries=2)
    spool_dir = tmp_path / "spool"
    try:
        transport.send_event(event("sess_spool", 9))
        transport.flush(timeout=5.0)

        # Wait for either the live append file or a claimed replay file to
        # appear (opportunistic replay may claim it immediately while offline).
        spool_path = spool_dir / "sess_spool.jsonl"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not read_spool_records(spool_dir):
            time.sleep(0.005)
        assert [r["seq"] for r in read_spool_records(spool_dir)] == [9]

        # Network restored: flip the default action to a 200 accept, then a
        # later flush replays the spool file through the HTTP poster.
        fake.set_default(FakePoster._ok_action({"accepted": 1, "rejected": []}))
        before = fake.success_count
        transport.flush(timeout=5.0)
        assert fake.wait_success(count=before + 1, timeout=5.0)

        # Spool data deleted once accepted; replay went through the HTTP poster.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and read_spool_records(spool_dir):
            time.sleep(0.005)
        assert read_spool_records(spool_dir) == []

        replayed = [
            payload
            for url, payload in fake.event_calls
            if url.endswith("/sess_spool/events")
        ][-1]
        assert [e["seq"] for e in replayed["events"]] == [9]
    finally:
        transport.close()


# -- graceful + idempotent flush/close --------------------------------------


def test_flush_and_close_are_idempotent_and_do_not_deadlock(fake, tmp_path):
    transport = make_transport(fake, tmp_path)

    transport.send_event(event("sess_g", 1))
    # Multiple flushes are safe.
    transport.flush(timeout=5.0)
    transport.flush(timeout=5.0)
    assert fake.wait_success(count=1, timeout=5.0)

    thread = transport._thread
    assert thread is not None

    # close() is graceful and stops the background thread.
    transport.close()
    assert transport.closed is True
    if thread is not None:
        thread.join(timeout=5.0)
        assert not thread.is_alive(), "background thread should stop on close()"

    # close() again is a no-op (idempotent), no deadlock.
    transport.close()
    assert transport.closed is True


def test_send_after_close_is_swallowed_not_raised(fake, tmp_path):
    transport = make_transport(fake, tmp_path)
    transport.close()
    # Must never raise into the host agent, even when closed.
    transport.send_event(event("sess_late", 1))
    assert transport.closed is True


# -- bounded queue: overflow spills to the spool, never blocks/drops ---------


def test_queue_overflow_spills_to_spool_without_blocking(fake, tmp_path):
    # Keep the network down so the flusher cannot drain the queue, then emit far
    # more events than the tiny bounded queue holds. Overflow must spill to the
    # spool rather than block the caller or silently vanish.
    fake.set_default(FakePoster._urlerror_action())
    transport = make_transport(
        fake, tmp_path, queue_maxsize=2, max_retries=0, flush_interval=10.0
    )
    spool_dir = tmp_path / "spool"
    try:
        # Stop the flusher from draining: it parks on a long flush_interval and
        # any post it makes fails (URLError). Emit 50 events into a size-2 queue.
        for seq in range(50):
            transport.send_event(event("sess_of", seq))

        # The overflow that could not be enqueued is spilled to the spool.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not read_spool_records(spool_dir):
            time.sleep(0.005)
        spilled = {r["seq"] for r in read_spool_records(spool_dir)}
        assert spilled, "queue overflow must spill to the spool"
        # At least the events beyond the queue capacity were spilled; none lost.
        assert len(spilled) >= 50 - 2
    finally:
        transport.close()


# -- spool size cap: oldest replayable files pruned first -------------------


def test_spool_cap_prunes_oldest_replayable_file(fake, tmp_path):
    transport = make_transport(fake, tmp_path)
    spool_dir = tmp_path / "spool"
    try:
        # A cap that holds one spool file (~163 bytes) but not two, so the
        # second write forces a prune of the oldest.
        transport.max_spool_bytes = 200

        transport._spool("sess_old", [event("sess_old", 1)])
        old_path = spool_dir / "sess_old.jsonl"
        assert old_path.exists()
        # Ensure a strictly older mtime for deterministic prune ordering.
        import os

        os.utime(old_path, (1.0, 1.0))

        # Second spool write pushes total over the cap and prunes the oldest.
        transport._spool("sess_new", [event("sess_new", 2)])

        assert not old_path.exists(), "oldest replayable spool file should be pruned"
        assert (spool_dir / "sess_new.jsonl").exists()
    finally:
        transport.close()


def test_spool_cap_retains_dead_letter_files(fake, tmp_path):
    transport = make_transport(fake, tmp_path)
    spool_dir = tmp_path / "spool"
    try:
        transport.max_spool_bytes = 40
        # Dead-letter records are forensic and must survive pruning.
        transport._dead_letter("sess_dl", [event("sess_dl", 1)], reason="http_413")
        dl_path = spool_dir / "dead-letter" / "sess_dl.jsonl"
        assert dl_path.exists()

        # Spool a replayable file that pushes over cap; only it may be pruned.
        transport._spool("sess_keep", [event("sess_keep", 2)])
        transport._prune_spool()

        assert dl_path.exists(), "dead-letter files must never be pruned"
    finally:
        transport.close()


# -- non-retryable 4xx (e.g. 413) dead-letters instead of dropping ----------


def test_unexpected_4xx_dead_letters_instead_of_dropping(fake, tmp_path):
    fake.http_error(413)  # payload too large: not in permanent set, not 429/5xx
    transport = make_transport(fake, tmp_path, max_retries=5)
    try:
        transport.send_event(event("sess_413", 4))
        transport.flush(timeout=5.0)

        dl_path = tmp_path / "spool" / "dead-letter" / "sess_413.jsonl"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not dl_path.exists():
            time.sleep(0.005)
        assert dl_path.exists(), "unexpected 4xx must dead-letter, not silently drop"

        records = read_jsonl(dl_path)
        assert [r["seq"] for r in records] == [4]
        assert records[0]["_reject_reason"] == "http_413"

        # 413 is not retried (single POST) and not spooled for replay.
        assert len(fake.event_calls) == 1
        assert not (tmp_path / "spool" / "sess_413.jsonl").exists()
    finally:
        transport.close()


def test_safe_drop_409_is_dropped_not_dead_lettered(fake, tmp_path):
    fake.http_error(409)  # duplicate: genuinely safe to drop
    transport = make_transport(fake, tmp_path, max_retries=5)
    try:
        transport.send_event(event("sess_409", 5))
        transport.flush(timeout=5.0)

        # Give the async flusher a moment; nothing should be written either way.
        time.sleep(0.1)
        assert not (tmp_path / "spool" / "dead-letter" / "sess_409.jsonl").exists()
        assert not (tmp_path / "spool" / "sess_409.jsonl").exists()
        assert len(fake.event_calls) == 1
    finally:
        transport.close()


def test_replay_claims_spool_file_before_posting(fake, tmp_path):
    transport = make_transport(fake, tmp_path)
    spool_dir = tmp_path / "spool"
    spool_path = spool_dir / "sess_live.jsonl"
    try:
        transport._spool("sess_live", [event("sess_live", 1)])

        def post(path, payload):
            # A concurrent spill for the same session must create/append the
            # live sess_live.jsonl, not mutate the claimed replay file.
            transport._spool("sess_live", [event("sess_live", 2)])
            return {"accepted": len(payload["events"]), "rejected": []}

        transport._post = post  # type: ignore[method-assign]
        transport._replay_spool_file(spool_path)

        assert spool_path.exists()
        assert [r["seq"] for r in read_jsonl(spool_path)] == [2]
        assert list(spool_dir.glob("*.replaying-*.jsonl")) == []
    finally:
        transport.close()


def test_replay_keeps_unaccounted_claimed_events_and_dead_letters_rejects(fake, tmp_path):
    transport = make_transport(fake, tmp_path)
    spool_dir = tmp_path / "spool"
    spool_path = spool_dir / "sess_ambiguous.jsonl"
    try:
        transport._spool(
            "sess_ambiguous",
            [event("sess_ambiguous", 1), event("sess_ambiguous", 2)],
        )
        transport._post = lambda path, payload: {  # type: ignore[method-assign]
            "accepted": 0,
            "rejected": [
                {
                    "index": 1,
                    "idempotency_key": "sess_ambiguous:nonce:2",
                    "reason": "schema_invalid",
                }
            ],
        }

        transport._replay_spool_file(spool_path)

        assert not spool_path.exists()
        claimed = list(spool_dir.glob("*.replaying-*.jsonl"))
        assert len(claimed) == 1
        assert [r["seq"] for r in read_jsonl(claimed[0])] == [1]

        dl_path = spool_dir / "dead-letter" / "sess_ambiguous.jsonl"
        assert [r["seq"] for r in read_jsonl(dl_path)] == [2]
    finally:
        transport.close()


def test_ambiguous_live_2xx_spools_unaccounted_events(fake, tmp_path):
    transport = make_transport(fake, tmp_path)
    spool_path = tmp_path / "spool" / "sess_live_ambiguous.jsonl"
    try:
        transport._post = lambda path, payload: {  # type: ignore[method-assign]
            "accepted": 0,
            "rejected": [],
        }
        transport._post_session_events(
            "sess_live_ambiguous", [event("sess_live_ambiguous", 1)]
        )

        assert spool_path.exists()
        assert [r["seq"] for r in read_jsonl(spool_path)] == [1]
    finally:
        transport.close()


def test_flush_timeout_does_not_block_on_full_queue_sentinel(fake, tmp_path):
    class AliveThread:
        def is_alive(self):
            return True

    transport = make_transport(fake, tmp_path, queue_maxsize=1)
    try:
        transport._queue.put_nowait(event("sess_full", 1))
        transport._thread = AliveThread()  # type: ignore[assignment]

        started = time.monotonic()
        transport.flush(timeout=0.01)

        assert time.monotonic() - started < 0.5
    finally:
        transport._thread = None
        transport.close()
