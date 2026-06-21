"""Promptetheus event schema contract.

This module is the Python source of truth for trace events. It intentionally
keeps runtime validation lightweight and dependency-free; server-side ingestion
can layer stricter payload validation on top of this envelope contract.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, NotRequired, TypeAlias, TypedDict


EventType: TypeAlias = Literal[
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
]

EVENT_TYPES: tuple[str, ...] = (
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


class BaseEvent(TypedDict):
    """Common envelope carried by every Promptetheus event.

    span_id and parent_id are optional run-tree fields. They are present only
    when the event was emitted inside an active Session.span(...) block; absent
    them an event is a flat, top-level entry in the timeline. The timeline still
    orders by (session_id, seq); spans add tree structure on top of that order,
    they do not replace seq.
    """

    type: str
    session_id: str
    timestamp: str
    seq: int
    idempotency_key: str
    payload: dict[str, Any]
    metadata: NotRequired[dict[str, Any]]
    # Run-tree fields (optional, backward compatible). span_id is the id of the
    # span this event belongs to; parent_id is the enclosing span's id (or None
    # for a top-level span).
    span_id: NotRequired[str]
    parent_id: NotRequired[str | None]


class UserMessageEvent(BaseEvent, total=False):
    type: Literal["user_message"]


class VoiceMessageMetadata(TypedDict, total=False):
    """Optional timing and conversation signals for voice message payloads."""

    channel: Literal["voice"]
    speaker: Literal["user", "agent"]
    start_ms: int
    end_ms: int
    interrupted: bool
    sentiment: float


class AgentMessageEvent(BaseEvent, total=False):
    type: Literal["agent_message"]


class ToolCallEvent(BaseEvent, total=False):
    type: Literal["tool_call"]


class ToolResultEvent(BaseEvent, total=False):
    type: Literal["tool_result"]


class RetrievalDocument(TypedDict, total=False):
    id: str
    content: str
    score: float
    source: str
    metadata: dict[str, Any]


class RetrievalEvent(BaseEvent, total=False):
    type: Literal["retrieval"]


class BrowserActionEvent(BaseEvent, total=False):
    type: Literal["browser_action"]


class DomSnapshotEvent(BaseEvent, total=False):
    type: Literal["dom_snapshot"]


class ScreenshotEvent(BaseEvent, total=False):
    type: Literal["screenshot"]


class ReplayArtifactEvent(BaseEvent, total=False):
    type: Literal["replay_artifact"]


class GoalCheckEvent(BaseEvent, total=False):
    type: Literal["goal_check"]


class StateChangePayload(TypedDict, total=False):
    """Payload shape for state_change events, including span markers.

    A generic state_change carries name plus optional before and after. The
    span markers reuse this event type: span_start and span_end set name to that
    marker string and carry span_name. span_end additionally carries duration_ms,
    the wall-clock elapsed between span_start and span_end rounded to whole
    milliseconds. duration_ms is optional so span_end events recorded before it
    existed still validate.
    """

    name: str
    before: Any
    after: Any
    span_name: str
    duration_ms: int


class StateChangeEvent(BaseEvent, total=False):
    # The payload field is inherited from BaseEvent as a generic mapping; the
    # concrete shape, including the span_end duration_ms field, is documented by
    # StateChangePayload above so the schema stays the source of truth.
    type: Literal["state_change"]


class SessionEndEvent(BaseEvent, total=False):
    type: Literal["session_end"]


class LlmCallEvent(BaseEvent, total=False):
    """Reserved event type for future LLM framework adapters."""

    type: Literal["llm_call"]


class ScoreEvent(BaseEvent, total=False):
    """A score / feedback attached to the session (human or automated).

    Payload: name (str), value (number or bool), comment (optional str),
    source (optional str, e.g. human or auto).
    """

    type: Literal["score"]


class ErrorEvent(BaseEvent, total=False):
    """A captured error/exception, richer than a tool_result error string.

    Payload: message (str), error_type (optional str), traceback (optional str),
    handled (optional bool).
    """

    type: Literal["error"]


class MetricEvent(BaseEvent, total=False):
    """An arbitrary numeric metric emitted during the run.

    Payload: name (str), value (number), unit (optional str).
    """

    type: Literal["metric"]


Event: TypeAlias = (
    UserMessageEvent
    | AgentMessageEvent
    | ToolCallEvent
    | ToolResultEvent
    | RetrievalEvent
    | BrowserActionEvent
    | DomSnapshotEvent
    | ScreenshotEvent
    | ReplayArtifactEvent
    | GoalCheckEvent
    | StateChangeEvent
    | SessionEndEvent
    | LlmCallEvent
    | ScoreEvent
    | ErrorEvent
    | MetricEvent
)


_REQUIRED_ENVELOPE_FIELDS = (
    "type",
    "session_id",
    "timestamp",
    "seq",
    "idempotency_key",
    "payload",
)


def validate_event(event: Mapping[str, Any]) -> None:
    """Validate the common Promptetheus event envelope.

    Raises:
        TypeError: if event or an envelope field has the wrong type.
        ValueError: if required fields are missing or envelope values are invalid.
    """

    if not isinstance(event, Mapping):
        raise TypeError("event must be a mapping")

    missing = [field for field in _REQUIRED_ENVELOPE_FIELDS if field not in event]
    if missing:
        raise ValueError(
            f"event missing required envelope field(s): {', '.join(missing)}"
        )

    event_type = event["type"]
    if not isinstance(event_type, str):
        raise TypeError("event.type must be a string")
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type!r}")

    session_id = event["session_id"]
    if not isinstance(session_id, str):
        raise TypeError("event.session_id must be a string")
    if not session_id:
        raise ValueError("event.session_id must be nonempty")

    timestamp = event["timestamp"]
    if not isinstance(timestamp, str):
        raise TypeError("event.timestamp must be a string")

    seq = event["seq"]
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise TypeError("event.seq must be an integer")
    if seq < 0:
        raise ValueError("event.seq must be >= 0")

    idempotency_key = event["idempotency_key"]
    if not isinstance(idempotency_key, str):
        raise TypeError("event.idempotency_key must be a string")
    if not idempotency_key:
        raise ValueError("event.idempotency_key must be nonempty")

    if not isinstance(event["payload"], Mapping):
        raise TypeError("event.payload must be a mapping")
    payload = event["payload"]

    if event_type == "llm_call":
        _validate_llm_call_payload(payload)

    # Optional run-tree fields. Events without them validate exactly as before;
    # when present they are lightly type-checked. span_id must be a nonempty
    # string; parent_id must be a string or None.
    if "span_id" in event:
        span_id = event["span_id"]
        if not isinstance(span_id, str):
            raise TypeError("event.span_id must be a string")
        if not span_id:
            raise ValueError("event.span_id must be nonempty")

    if "parent_id" in event:
        parent_id = event["parent_id"]
        if parent_id is not None and not isinstance(parent_id, str):
            raise TypeError("event.parent_id must be a string or None")


def _validate_llm_call_payload(payload: Mapping[str, Any]) -> None:
    """Validate the reserved llm_call payload contract."""

    forbidden = [key for key in ("prompt", "messages") if key in payload]
    if forbidden:
        raise ValueError(
            "llm_call payload must use prompt_ref/messages_ref, not raw "
            f"{', '.join(forbidden)}"
        )

    model = payload.get("model")
    if not isinstance(model, str):
        raise TypeError("llm_call.payload.model must be a string")
    if not model:
        raise ValueError("llm_call.payload.model must be nonempty")

    for key in ("input_tokens", "output_tokens", "latency_ms"):
        if key in payload:
            value = payload[key]
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"llm_call.payload.{key} must be an integer")

    for key in ("prompt_ref", "messages_ref"):
        if key in payload and not isinstance(payload[key], str):
            raise TypeError(f"llm_call.payload.{key} must be a string")


def event_schema() -> dict[str, Any]:
    """Return a JSON-schema-ish plain dict for docs and parity tests."""

    return {
        "title": "PromptetheusEvent",
        "type": "object",
        "required": list(_REQUIRED_ENVELOPE_FIELDS),
        "additionalProperties": True,
        "properties": {
            "type": {"type": "string", "enum": list(EVENT_TYPES)},
            "session_id": {"type": "string", "minLength": 1},
            "timestamp": {"type": "string"},
            "seq": {"type": "integer", "minimum": 0},
            "idempotency_key": {"type": "string", "minLength": 1},
            "payload": {"type": "object"},
            "metadata": {"type": "object"},
            "span_id": {"type": "string", "minLength": 1},
            "parent_id": {"type": ["string", "null"]},
        },
        "definitions": {
            "voice_message_metadata": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": ["voice"]},
                    "speaker": {"type": "string", "enum": ["user", "agent"]},
                    "start_ms": {"type": "integer", "minimum": 0},
                    "end_ms": {"type": "integer", "minimum": 0},
                    "interrupted": {"type": "boolean"},
                    "sentiment": {"type": "number", "minimum": -1, "maximum": 1},
                },
            }
        },
        "events": {
            "user_message": {
                "properties": {
                    "content": {"type": "string"},
                    "metadata": {"$ref": "#/definitions/voice_message_metadata"},
                }
            },
            "agent_message": {
                "properties": {
                    "content": {"type": "string"},
                    "metadata": {"$ref": "#/definitions/voice_message_metadata"},
                }
            },
            "tool_call": {
                "properties": {
                    "tool_name": {"type": "string"},
                    "arguments": {"type": "object"},
                    "call_id": {"type": "string"},
                    "metadata": {"type": "object"},
                }
            },
            "tool_result": {
                "properties": {
                    "call_id": {"type": "string"},
                    "result": {},
                    "error": {"type": "string"},
                    "metadata": {"type": "object"},
                }
            },
            "retrieval": {
                "properties": {
                    "query": {"type": "string"},
                    "documents": {"type": "array"},
                    "metadata": {"type": "object"},
                }
            },
            "browser_action": {
                "properties": {
                    "action": {"type": "string"},
                    "target": {"type": "string"},
                    "url": {"type": "string"},
                    "metadata": {"type": "object"},
                }
            },
            "dom_snapshot": {
                "properties": {
                    "url": {"type": "string"},
                    "visible_text": {"type": "string"},
                    "selected_values": {"type": "object"},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                    "metadata": {"type": "object"},
                }
            },
            "screenshot": {
                "properties": {
                    "artifact_id": {"type": "string"},
                    "storage_path": {"type": "string"},
                    "size_bytes": {"type": "integer", "minimum": 0},
                    "source_type": {"type": "string", "enum": ["bytes", "path"]},
                    "metadata": {"type": "object"},
                }
            },
            "replay_artifact": {
                "properties": {
                    "artifact_id": {"type": "string"},
                    "artifact_type": {
                        "type": "string",
                        "enum": ["screen_recording", "audio_recording"],
                    },
                    "storage_path": {"type": "string"},
                    "started_at": {"type": "string"},
                    "ended_at": {"type": "string"},
                    "duration_ms": {"type": "integer"},
                    "event_time_map": {
                        "type": "object",
                        "additionalProperties": {"type": "integer"},
                    },
                    "metadata": {"type": "object"},
                }
            },
            "goal_check": {
                "properties": {
                    "passed": {"type": "boolean"},
                    "mismatches": {"type": "array", "items": {"type": "string"}},
                    "metadata": {"type": "object"},
                }
            },
            "state_change": {
                "properties": {
                    "name": {"type": "string"},
                    "before": {},
                    "after": {},
                    # span_start / span_end markers carry the span name. span_end
                    # additionally carries duration_ms, the wall-clock elapsed
                    # between span_start and span_end rounded to whole
                    # milliseconds. duration_ms is optional so older span_end
                    # events recorded without it still validate.
                    "span_name": {"type": "string"},
                    "duration_ms": {"type": "integer", "minimum": 0},
                    "metadata": {"type": "object"},
                }
            },
            "session_end": {
                "properties": {
                    "status": {"type": "string"},
                    "error": {"type": "string"},
                    "metadata": {"type": "object"},
                }
            },
            "llm_call": {
                "reserved": True,
                "properties": {
                    "model": {"type": "string"},
                    "prompt_ref": {"type": "string"},
                    "messages_ref": {"type": "string"},
                    "input_tokens": {"type": "integer"},
                    "output_tokens": {"type": "integer"},
                    "latency_ms": {"type": "integer"},
                    "metadata": {"type": "object"},
                },
            },
            "score": {
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": ["number", "boolean"]},
                    "comment": {"type": "string"},
                    "source": {"type": "string"},
                    "metadata": {"type": "object"},
                }
            },
            "error": {
                "properties": {
                    "message": {"type": "string"},
                    "error_type": {"type": "string"},
                    "traceback": {"type": "string"},
                    "handled": {"type": "boolean"},
                    "metadata": {"type": "object"},
                }
            },
            "metric": {
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "metadata": {"type": "object"},
                }
            },
        },
    }


__all__ = [
    "AgentMessageEvent",
    "BaseEvent",
    "BrowserActionEvent",
    "DomSnapshotEvent",
    "EVENT_TYPES",
    "ErrorEvent",
    "Event",
    "EventType",
    "GoalCheckEvent",
    "LlmCallEvent",
    "MetricEvent",
    "ReplayArtifactEvent",
    "RetrievalDocument",
    "RetrievalEvent",
    "ScoreEvent",
    "ScreenshotEvent",
    "SessionEndEvent",
    "StateChangePayload",
    "StateChangeEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "UserMessageEvent",
    "VoiceMessageMetadata",
    "event_schema",
    "validate_event",
]
