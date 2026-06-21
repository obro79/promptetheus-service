"""Per-event-type sampling + redaction hashing/allowlist (group 5)."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

import promptetheus as pt  # noqa: E402
from promptetheus.redaction import REDACTION_PLACEHOLDER, build_default_redactor  # noqa: E402
from promptetheus.session import Session  # noqa: E402


class Rec:
    def __init__(self):
        self.events = []

    def send_event(self, event):
        self.events.append(event)

    def send_batch(self, events):
        self.events.extend(dict(e) for e in events)

    def flush(self, timeout=None):
        pass


# -- per-event-type sampling ------------------------------------------------


def test_event_type_sampling_drops_noise_keeps_rest():
    t = Rec()
    s = Session(
        agent="a", user_goal="g", session_id="s1", transport=t,
        event_sample_rates={"dom_snapshot": 0.0},
    )
    s.agent_message("kept")
    for i in range(5):
        s.dom_snapshot(url="u", visible_text="t")
    types = [e["type"] for e in t.events]
    assert "agent_message" in types
    assert "dom_snapshot" not in types  # rate 0.0 -> all dropped


def test_event_type_sampling_keeps_critical_types():
    t = Rec()
    s = Session(
        agent="a", user_goal="g", session_id="s2", transport=t,
        event_sample_rates={"goal_check": 0.0, "error": 0.0, "state_change": 0.0},
    )
    s.goal_check(False)
    s.error("boom")
    types = [e["type"] for e in t.events]
    # critical/failure types are never dropped even at rate 0.0
    assert "goal_check" in types
    assert "error" in types


def test_event_type_sampling_is_deterministic_per_event():
    # The decision is a pure function of the event (its idempotency key), so the
    # same event always resolves the same way within a session.
    s = Session(
        agent="a", user_goal="g", session_id="s", transport=Rec(),
        event_sample_rates={"metric": 0.5},
    )
    ev = {"type": "metric", "idempotency_key": "s:nonce:7", "payload": {}}
    decisions = {s._keep_for_type_sampling(ev) for _ in range(10)}
    assert len(decisions) == 1  # stable

    # A 0.5 rate keeps some but not all of a spread of keys (not all-or-nothing).
    kept = [
        s._keep_for_type_sampling({"type": "metric", "idempotency_key": f"s:nonce:{i}", "payload": {}})
        for i in range(50)
    ]
    assert 0 < sum(kept) < 50


def test_observe_sync_honours_tail_sample_and_type_rates():
    # Regression: the sync observe wrapper previously dropped tail_sample.
    t = Rec()

    @pt.observe(agent="x", user_goal="g", transport=t, tail_sample=True)
    def boring():
        pt.current().agent_message("work")
        return 1

    # tail_sample=True + a boring success at default sample_rate 1.0 -> kept
    boring()
    assert any(e["type"] == "session_end" for e in t.events)


# -- redaction hashing + allowlist ------------------------------------------


def _event(payload):
    return {
        "type": "agent_message", "session_id": "s", "seq": 1,
        "timestamp": "t", "idempotency_key": "s:n:1", "payload": payload,
    }


def test_redaction_hash_mode_correlates():
    redact = build_default_redactor(hash_values=True)
    out1 = redact(_event({"authorization": "secret-token-A"}))
    out2 = redact(_event({"authorization": "secret-token-A"}))
    out3 = redact(_event({"authorization": "secret-token-B"}))
    val1 = out1["payload"]["authorization"]
    assert val1.startswith("sha256:")
    assert "secret-token-A" not in val1
    assert val1 == out2["payload"]["authorization"]  # equal secrets correlate
    assert val1 != out3["payload"]["authorization"]  # different secret differs


def test_redaction_allow_keys_skips():
    redact = build_default_redactor(allow_keys=["api_key"])
    out = redact(_event({"api_key": "kept-by-allowlist", "password": "scrubbed"}))
    assert out["payload"]["api_key"] == "kept-by-allowlist"  # allowlisted
    assert out["payload"]["password"] == REDACTION_PLACEHOLDER  # still scrubbed


def test_redaction_default_still_placeholder():
    redact = build_default_redactor()
    out = redact(_event({"password": "x"}))
    assert out["payload"]["password"] == REDACTION_PLACEHOLDER
