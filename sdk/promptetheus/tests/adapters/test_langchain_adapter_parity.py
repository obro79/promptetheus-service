"""LangChain-driven sessions must use the same envelope as hand instrumentation."""

from __future__ import annotations

import sys
import types
import uuid

import pytest

from promptetheus.session import Session

_ENVELOPE_KEYS = frozenset(
    {"type", "session_id", "timestamp", "seq", "idempotency_key", "payload"}
)


class RecordingTransport:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def send_event(self, event: dict) -> None:
        self.events.append(dict(event))

    def flush(self, timeout=None) -> None:
        pass


@pytest.fixture()
def fake_langchain(monkeypatch):
    class BaseCallbackHandler:
        def __init__(self, *a, **k):
            pass

    root = types.ModuleType("langchain_core")
    callbacks = types.ModuleType("langchain_core.callbacks")
    callbacks.BaseCallbackHandler = BaseCallbackHandler
    root.callbacks = callbacks
    monkeypatch.setitem(sys.modules, "langchain_core", root)
    monkeypatch.setitem(sys.modules, "langchain_core.callbacks", callbacks)


def test_langchain_event_types_subset_of_session_helpers(fake_langchain) -> None:
    from promptetheus.adapters.langchain import PromptetheusCallbackHandler

    hand = RecordingTransport()
    with Session(agent="a", user_goal="g", session_id="hand_sess", transport=hand) as session:
        session.user_message("u")
        session.agent_message("a")
        session.tool_call("t", {}, call_id="c1")
        session.tool_result("c1", result="ok")
        session.llm_call("gpt-4o", input_tokens=1, output_tokens=2)

    adapter = RecordingTransport()
    with Session(agent="a", user_goal="g", session_id="lc_sess", transport=adapter) as session:
        handler = PromptetheusCallbackHandler(session)
        rid = uuid.uuid4()
        handler.on_llm_start({"name": "FakeLLM"}, ["hi"], run_id=rid)
        handler.on_tool_start({"name": "search"}, "q", run_id=uuid.uuid4())
        handler.on_tool_end("found", run_id=uuid.uuid4())

        class Result:
            llm_output = {"token_usage": {"prompt_tokens": 1, "completion_tokens": 1}}
            generations: list = []

        handler.on_llm_end(Result(), run_id=rid)

    hand_types = {e["type"] for e in hand.events}
    adapter_types = {e["type"] for e in adapter.events}
    assert adapter_types.issubset(hand_types | {"state_change", "session_end"})

    for event in adapter.events:
        assert _ENVELOPE_KEYS.issubset(event.keys())
        assert event["session_id"] == "lc_sess"
        assert isinstance(event["idempotency_key"], str)
