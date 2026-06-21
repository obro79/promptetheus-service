"""Property-based tests for the event-envelope contract (schema.py).

Uses hypothesis to generate many event envelopes and asserts two properties:

- validate_event accepts every well-formed envelope (all required fields
  present and well-typed, optional run-tree fields well-typed when present),
- validate_event rejects malformed envelopes (a required field dropped, or a
  field given the wrong type) by raising TypeError or ValueError.

It also checks the idempotency-key format used by Session.event,
session_id:nonce:seq, round-trips: building the key and splitting it back out
recovers the original parts, and a key built that way passes validation.
"""

from __future__ import annotations

import string

from hypothesis import given
from hypothesis import strategies as st

from promptetheus.schema import EVENT_TYPES, validate_event


# Tokens used for session ids / nonces. Kept free of ':' so the idempotency-key
# round-trip split is unambiguous, and nonempty so session_id validation passes.
_tokens = st.text(
    alphabet=string.ascii_letters + string.digits + "_-",
    min_size=1,
    max_size=24,
)

_payloads = st.dictionaries(
    keys=st.text(min_size=0, max_size=8),
    values=st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=16),
    ),
    max_size=4,
)


@st.composite
def well_formed_events(draw: st.DrawFn) -> dict:
    """Generate an envelope that validate_event must accept."""

    session_id = draw(_tokens)
    nonce = draw(_tokens)
    seq = draw(st.integers(min_value=0, max_value=1_000_000))
    event_type = draw(st.sampled_from(EVENT_TYPES))
    payload = (
        {
            "model": draw(_tokens),
            "prompt_ref": f"artifact://{draw(_tokens)}",
            "input_tokens": draw(st.integers(min_value=0, max_value=1_000_000)),
            "output_tokens": draw(st.integers(min_value=0, max_value=1_000_000)),
            "latency_ms": draw(st.integers(min_value=0, max_value=1_000_000)),
        }
        if event_type == "llm_call"
        else draw(_payloads)
    )
    event: dict = {
        "type": event_type,
        "session_id": session_id,
        "timestamp": draw(st.text(min_size=0, max_size=32)),
        "seq": seq,
        "idempotency_key": f"{session_id}:{nonce}:{seq}",
        "payload": payload,
    }
    # Optionally attach a well-typed metadata mapping.
    if draw(st.booleans()):
        event["metadata"] = draw(_payloads)
    # Optionally attach well-typed run-tree fields.
    if draw(st.booleans()):
        event["span_id"] = draw(_tokens)
        event["parent_id"] = draw(st.one_of(st.none(), _tokens))
    return event


@given(well_formed_events())
def test_validate_accepts_well_formed_events(event: dict) -> None:
    # Must not raise for any well-formed envelope.
    validate_event(event)


_REQUIRED = ("type", "session_id", "timestamp", "seq", "idempotency_key", "payload")


@given(well_formed_events(), st.sampled_from(_REQUIRED))
def test_validate_rejects_missing_required_field(event: dict, field: str) -> None:
    broken = dict(event)
    broken.pop(field, None)
    try:
        validate_event(broken)
    except (TypeError, ValueError):
        return
    raise AssertionError(f"validate_event accepted an envelope missing {field!r}")


@given(well_formed_events())
def test_validate_rejects_unknown_event_type(event: dict) -> None:
    broken = dict(event)
    broken["type"] = "definitely_not_a_real_event_type"
    try:
        validate_event(broken)
    except ValueError:
        return
    raise AssertionError("validate_event accepted an unknown event type")


@given(
    well_formed_events(),
    st.sampled_from(["seq", "session_id", "type", "idempotency_key", "payload"]),
)
def test_validate_rejects_wrong_typed_field(event: dict, field: str) -> None:
    broken = dict(event)
    # Inject a value of a deliberately wrong type per field.
    wrong = {
        "seq": "not-an-int",
        "session_id": 123,
        "type": 7,
        "idempotency_key": 42,
        "payload": ["not", "a", "mapping"],
    }[field]
    broken[field] = wrong
    try:
        validate_event(broken)
    except (TypeError, ValueError):
        return
    raise AssertionError(f"validate_event accepted a wrong-typed {field!r}")


@given(well_formed_events())
def test_validate_rejects_negative_seq(event: dict) -> None:
    broken = dict(event)
    broken["seq"] = -1
    try:
        validate_event(broken)
    except ValueError:
        return
    raise AssertionError("validate_event accepted a negative seq")


# -- idempotency-key round-trip --------------------------------------------


@given(_tokens, _tokens, st.integers(min_value=0, max_value=1_000_000))
def test_idempotency_key_round_trips(session_id: str, nonce: str, seq: int) -> None:
    # The Session.event format is session_id:nonce:seq. Since the tokens contain
    # no ':', splitting on ':' recovers the three components exactly.
    key = f"{session_id}:{nonce}:{seq}"
    parts = key.split(":")
    assert parts == [session_id, nonce, str(seq)]
    # rsplit on the last colon recovers seq even if a token had a colon-free body.
    base, _, recovered_seq = key.rpartition(":")
    assert recovered_seq == str(seq)
    assert base == f"{session_id}:{nonce}"


@given(well_formed_events())
def test_idempotency_key_built_format_validates(event: dict) -> None:
    # An envelope whose key uses the documented format validates cleanly.
    validate_event(event)
    assert event["idempotency_key"].count(":") >= 2
