from __future__ import annotations

import sys
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.schema import EVENT_TYPES, event_schema, validate_event  # noqa: E402


EXPECTED_EVENT_TYPES = (
    "user_message",
    "agent_message",
    "tool_call",
    "tool_result",
    "retrieval",
    "browser_action",
    "dom_snapshot",
    "screenshot",
    "replay_artifact",
    "goal_check",
    "state_change",
    "session_end",
    "llm_call",
    "score",
    "error",
    "metric",
)


def base_event(**overrides: object) -> dict[str, object]:
    event = {
        "type": "browser_action",
        "session_id": "sess_01J9XQ",
        "timestamp": "2026-06-12T12:34:56.000Z",
        "seq": 12,
        "idempotency_key": "sess_01J9XQ:b3f2:12",
        "payload": {"action": "click", "target": "button"},
    }
    event.update(overrides)
    return event


def test_event_types_are_contract_order() -> None:
    assert EVENT_TYPES == EXPECTED_EVENT_TYPES


def test_validate_event_accepts_known_event_with_envelope() -> None:
    validate_event(base_event())


@pytest.mark.parametrize("field", ["type", "session_id", "timestamp", "seq", "idempotency_key", "payload"])
def test_validate_event_rejects_missing_envelope_fields(field: str) -> None:
    event = base_event()
    del event[field]

    with pytest.raises(ValueError, match="missing required envelope"):
        validate_event(event)


@pytest.mark.parametrize(
    ("overrides", "error_type", "match"),
    [
        ({"type": "not_real"}, ValueError, "unknown event type"),
        ({"type": 123}, TypeError, "type must be a string"),
        ({"session_id": ""}, ValueError, "session_id must be nonempty"),
        ({"session_id": 123}, TypeError, "session_id must be a string"),
        ({"timestamp": 123}, TypeError, "timestamp must be a string"),
        ({"seq": -1}, ValueError, "seq must be >= 0"),
        ({"seq": 1.5}, TypeError, "seq must be an integer"),
        ({"seq": True}, TypeError, "seq must be an integer"),
        ({"idempotency_key": ""}, ValueError, "idempotency_key must be nonempty"),
        ({"idempotency_key": 123}, TypeError, "idempotency_key must be a string"),
        ({"payload": []}, TypeError, "payload must be a mapping"),
    ],
)
def test_validate_event_rejects_invalid_envelope(
    overrides: dict[str, object],
    error_type: type[Exception],
    match: str,
) -> None:
    with pytest.raises(error_type, match=match):
        validate_event(base_event(**overrides))


def test_event_schema_exports_envelope_and_event_types() -> None:
    schema = event_schema()

    assert schema["required"] == ["type", "session_id", "timestamp", "seq", "idempotency_key", "payload"]
    assert schema["properties"]["type"]["enum"] == list(EXPECTED_EVENT_TYPES)
    assert set(schema["events"]) == set(EXPECTED_EVENT_TYPES)
    assert schema["events"]["llm_call"]["reserved"] is True


def test_validate_llm_call_accepts_reference_payload() -> None:
    validate_event(
        base_event(
            type="llm_call",
            payload={
                "model": "gpt-4o-mini",
                "prompt_ref": "artifact://prompt",
                "messages_ref": "artifact://messages",
                "input_tokens": 10,
                "output_tokens": 5,
                "latency_ms": 42,
            },
        )
    )


@pytest.mark.parametrize(
    ("payload", "error_type", "match"),
    [
        ({}, TypeError, "model must be a string"),
        ({"model": ""}, ValueError, "model must be nonempty"),
        ({"model": "m", "prompt": "raw"}, ValueError, "prompt_ref/messages_ref"),
        ({"model": "m", "messages": []}, ValueError, "prompt_ref/messages_ref"),
        ({"model": "m", "input_tokens": 1.2}, TypeError, "input_tokens"),
        ({"model": "m", "output_tokens": True}, TypeError, "output_tokens"),
        ({"model": "m", "latency_ms": "42"}, TypeError, "latency_ms"),
        ({"model": "m", "prompt_ref": 123}, TypeError, "prompt_ref"),
        ({"model": "m", "messages_ref": []}, TypeError, "messages_ref"),
    ],
)
def test_validate_llm_call_rejects_invalid_payload(
    payload: dict[str, object],
    error_type: type[Exception],
    match: str,
) -> None:
    with pytest.raises(error_type, match=match):
        validate_event(base_event(type="llm_call", payload=payload))


def test_replay_artifact_schema_uses_storage_identity_not_public_url() -> None:
    replay_artifact = event_schema()["events"]["replay_artifact"]["properties"]

    assert "artifact_id" in replay_artifact
    assert "storage_path" in replay_artifact
    assert "public_url" not in replay_artifact


def test_screenshot_schema_uses_private_artifact_identity() -> None:
    screenshot = event_schema()["events"]["screenshot"]["properties"]

    assert "artifact_id" in screenshot
    assert "storage_path" in screenshot
    assert "size_bytes" in screenshot
    assert "source_type" in screenshot
    assert "public_url" not in screenshot
