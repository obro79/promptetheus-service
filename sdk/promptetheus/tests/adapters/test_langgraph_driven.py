"""Drive the real LangGraph adapter logic without installing langgraph/langchain.

The LangGraph adapter builds on a LangChain BaseCallbackHandler, so the same
fake-module trick used for the LangChain adapter exercises its real callback and
node-span-gating logic here, raising coverage past the import-safety contract in
test_langgraph.py.
"""

from __future__ import annotations

import sys
import types
import uuid
from typing import Any

import pytest

from promptetheus.session import Session


class RecordingTransport:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def flush(self, timeout: float | None = None) -> None:
        pass


@pytest.fixture
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
    return callbacks


def _adapter(session):
    from promptetheus.adapters.langgraph import LangGraphAdapter

    return LangGraphAdapter(session)


def _span_starts(transport):
    return [
        e
        for e in transport.events
        if e["type"] == "state_change" and (e["payload"] or {}).get("name") == "span_start"
    ]


def test_real_node_opens_a_span(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s1", transport=t)
    h = _adapter(s)
    rid = uuid.uuid4()
    h.on_chain_start({"name": "agent"}, {"in": 1}, run_id=rid)
    h.on_chain_end({"out": 2}, run_id=rid)
    starts = _span_starts(t)
    assert len(starts) == 1
    # span carries the node name
    assert any("agent" in str((e["payload"] or {})) for e in t.events)


def test_plumbing_node_does_not_open_a_span(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s2", transport=t)
    h = _adapter(s)
    for noise in ("RunnableSeq", "Pregel", "PregelLoop", "ChannelWrite", "__start__"):
        h.on_chain_start({"name": noise}, {}, run_id=uuid.uuid4())
    assert _span_starts(t) == []  # all plumbing skipped


def test_tool_start_end_emit_events(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s3", transport=t)
    h = _adapter(s)
    rid = uuid.uuid4()
    h.on_tool_start({"name": "search"}, "q", run_id=rid)
    h.on_tool_end("result", run_id=rid)
    types_seen = [e["type"] for e in t.events]
    assert "tool_call" in types_seen and "tool_result" in types_seen


def test_llm_end_emits_llm_call(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s4", transport=t)
    h = _adapter(s)
    rid = uuid.uuid4()
    h.on_llm_start({"name": "L"}, ["p"], run_id=rid, invocation_params={"model": "claude"})

    class Result:
        llm_output = {"token_usage": {"prompt_tokens": 3, "completion_tokens": 9}}
        generations: list[Any] = []

    h.on_llm_end(Result(), run_id=rid)
    call = [e for e in t.events if e["type"] == "llm_call"][0]["payload"]
    assert call["model"] == "claude"
    assert call["input_tokens"] == 3 and call["output_tokens"] == 9


def test_chain_error_closes_span(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s5", transport=t)
    h = _adapter(s)
    rid = uuid.uuid4()
    h.on_chain_start({"name": "agent"}, {}, run_id=rid)
    h.on_chain_error(RuntimeError("boom"), run_id=rid)
    ends = [
        e
        for e in t.events
        if e["type"] == "state_change" and (e["payload"] or {}).get("name") == "span_end"
    ]
    assert len(ends) == 1  # the open span was closed on error


def test_agent_action_and_text_emit_messages(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s6", transport=t)
    h = _adapter(s)
    h.on_agent_action(types.SimpleNamespace(log="deciding", tool="x"), run_id=uuid.uuid4())
    h.on_text("intermediate", run_id=uuid.uuid4())
    msgs = [e for e in t.events if e["type"] == "agent_message"]
    contents = " ".join(m["payload"]["content"] for m in msgs)
    assert "deciding" in contents and "intermediate" in contents
