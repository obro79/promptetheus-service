from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.testing import (  # noqa: E402
    CapturedEvents,
    capture_session,
    promptetheus_session_fixture,
)


def test_capture_session_records_events():
    with capture_session(agent="a", user_goal="g") as cap:
        assert isinstance(cap, CapturedEvents)
        cap.session.user_message("hello")
        cap.session.llm_call("gpt-4o", input_tokens=10, output_tokens=5)
        # Live view: events emitted so far are visible inside the block.
        assert "user_message" in cap.event_types
        assert "llm_call" in cap.event_types

    # session_started state_change is emitted on enter, session_end on exit.
    assert cap.event_types[0] == "state_change"
    assert cap.event_types[-1] == "session_end"
    assert cap.count("user_message") == 1
    assert cap.count("llm_call") == 1


def test_capture_session_uses_default_agent_and_goal():
    with capture_session() as cap:
        cap.session.agent_message("hi")
    assert cap.session.agent == "test-agent"
    assert cap.session.user_goal == "test goal"
    assert cap.count("agent_message") == 1


def test_of_type_and_count_and_last():
    with capture_session() as cap:
        cap.session.score("quality", 0.9)
        cap.session.score("quality", 0.2)
        cap.session.metric("tokens", 42)

    scores = cap.of_type("score")
    assert len(scores) == 2
    assert cap.count("score") == 2
    assert cap.count("metric") == 1
    assert cap.count("nonexistent") == 0

    last_score = cap.last("score")
    assert last_score is not None
    assert last_score["payload"]["value"] == 0.2
    assert cap.last("nonexistent") is None


def test_types_method_matches_event_types_property():
    with capture_session() as cap:
        cap.session.user_message("x")
    assert cap.types() == cap.event_types


def test_captured_events_is_iterable_and_sized():
    with capture_session() as cap:
        cap.session.user_message("x")
        cap.session.user_message("y")
    types = [event["type"] for event in cap]
    assert types == cap.event_types
    # state_change + 2 user_message + session_end
    assert len(cap) == len(cap.events)
    assert len(cap) >= 4


def test_transport_kwarg_is_ignored():
    # Even if a caller passes transport, the recording transport wins so events
    # are captured.
    with capture_session(transport="http", endpoint="http://example.com") as cap:
        cap.session.user_message("x")
    assert cap.count("user_message") == 1


def test_redact_kwarg_is_forwarded():
    with capture_session(redact="default") as cap:
        cap.session.user_message("my api_key is sk-secret1234567890")
    msg = cap.of_type("user_message")[0]
    assert "sk-secret1234567890" not in str(msg)


# pytest is importable in this environment, so exercise the fixture factory.
promptetheus_session = promptetheus_session_fixture(agent="fixtured", user_goal="fg")


def test_fixture_yields_a_working_captured_session(promptetheus_session):
    assert isinstance(promptetheus_session, CapturedEvents)
    assert promptetheus_session.session.agent == "fixtured"
    promptetheus_session.session.goal_check(passed=True)
    assert promptetheus_session.count("goal_check") == 1
