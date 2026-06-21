from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.redaction import REDACTION_PLACEHOLDER, build_default_redactor  # noqa: E402
from promptetheus.session import Session  # noqa: E402


def _event(payload: dict) -> dict:
    return {
        "type": "agent_message",
        "session_id": "s",
        "seq": 1,
        "timestamp": "2026-01-01T00:00:00Z",
        "idempotency_key": "s:nonce:1",
        "payload": payload,
    }


def test_default_redactor_scrubs_common_secrets():
    redact = build_default_redactor()
    out = redact(
        _event(
            {
                "content": "key sk-ABCDEFabcdef0123456789 and reach me at jo@example.com",
                "authorization": "Bearer abc.def.ghi",
            }
        )
    )
    assert "sk-ABCDEF" not in out["payload"]["content"]
    assert "jo@example.com" not in out["payload"]["content"]
    assert out["payload"]["content"].count(REDACTION_PLACEHOLDER) == 2
    # sensitive key name -> value blanked wholesale
    assert out["payload"]["authorization"] == REDACTION_PLACEHOLDER


def test_envelope_identity_fields_preserved():
    redact = build_default_redactor()
    out = redact(_event({"content": "benign"}))
    assert out["session_id"] == "s"
    assert out["idempotency_key"] == "s:nonce:1"
    assert out["type"] == "agent_message"
    assert out["seq"] == 1


def test_redactor_recurses_into_nested_structures():
    redact = build_default_redactor()
    out = redact(
        _event({"items": [{"password": "hunter2"}, {"note": "AKIAIOSFODNN7EXAMPLE here"}]})
    )
    assert out["payload"]["items"][0]["password"] == REDACTION_PLACEHOLDER
    assert "AKIAIOSFODNN7EXAMPLE" not in out["payload"]["items"][1]["note"]


def test_benign_content_untouched():
    redact = build_default_redactor()
    out = redact(_event({"content": "the meeting is at noon", "count": 3}))
    assert out["payload"]["content"] == "the meeting is at noon"
    assert out["payload"]["count"] == 3


def test_extra_patterns_and_keys():
    redact = build_default_redactor(
        extra_patterns=[("ticket", r"TKT-\d+")],
        extra_sensitive_keys=["ssn"],
    )
    out = redact(_event({"content": "ref TKT-99", "ssn": "111-22-3333"}))
    assert "TKT-99" not in out["payload"]["content"]
    assert out["payload"]["ssn"] == REDACTION_PLACEHOLDER


class RecordingTransport:
    def __init__(self):
        self.events = []

    def send_event(self, event):
        self.events.append(event)

    def flush(self, timeout=None):
        pass


def test_session_redact_default_string_enables_redactor():
    transport = RecordingTransport()
    session = Session(
        agent="a", user_goal="g", session_id="s", transport=transport, redact="default"
    )
    session.agent_message("token sk-ABCDEFabcdef0123456789")
    msg = next(e for e in transport.events if e["type"] == "agent_message")
    assert "sk-ABCDEF" not in msg["payload"]["content"]


def test_session_unknown_redact_string_is_noop():
    transport = RecordingTransport()
    session = Session(
        agent="a", user_goal="g", session_id="s", transport=transport, redact="nonsense"
    )
    session.agent_message("token sk-ABCDEFabcdef0123456789")
    msg = next(e for e in transport.events if e["type"] == "agent_message")
    assert "sk-ABCDEFabcdef0123456789" in msg["payload"]["content"]
