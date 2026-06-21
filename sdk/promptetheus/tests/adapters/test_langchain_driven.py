"""Drive the real LangChain adapter logic without installing langchain.

langchain_core is heavy and not installed here, so these tests inject a tiny
fake langchain_core.callbacks module exposing a BaseCallbackHandler base class.
That lets the real PromptetheusCallbackHandler subclass build and run, so the
adapter's actual callback-to-event mapping and usage extraction are exercised
(not just the import-safety contract covered in test_langchain.py).
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
    """Install a minimal fake langchain_core.callbacks with BaseCallbackHandler."""

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


def _handler(session):
    from promptetheus.adapters.langchain import PromptetheusCallbackHandler

    return PromptetheusCallbackHandler(session)


def _types(transport):
    return [e["type"] for e in transport.events]


def test_llm_end_emits_llm_call_with_llm_output_usage(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s1", transport=t)
    h = _handler(s)
    rid = uuid.uuid4()
    h.on_llm_start({"name": "FakeLLM"}, ["hi"], run_id=rid, invocation_params={"model": "gpt-4o"})

    class Result:
        llm_output = {"token_usage": {"prompt_tokens": 11, "completion_tokens": 5}}
        generations: list[Any] = []

    h.on_llm_end(Result(), run_id=rid)
    calls = [e for e in t.events if e["type"] == "llm_call"]
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload["model"] == "gpt-4o"
    assert payload["input_tokens"] == 11 and payload["output_tokens"] == 5
    assert calls[0]["metadata"]["run_id"] == str(rid)


def test_llm_end_falls_back_to_usage_metadata(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s2", transport=t)
    h = _handler(s)
    rid = uuid.uuid4()
    h.on_chat_model_start({"name": "Chat"}, [[]], run_id=rid)

    message = types.SimpleNamespace(usage_metadata={"input_tokens": 7, "output_tokens": 3})
    generation = types.SimpleNamespace(message=message)

    class Result:
        llm_output = None
        generations = [[generation]]

    h.on_llm_end(Result(), run_id=rid)
    payload = [e for e in t.events if e["type"] == "llm_call"][0]["payload"]
    assert payload["input_tokens"] == 7 and payload["output_tokens"] == 3


def test_tool_start_end_correlate_by_run_id(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s3", transport=t)
    h = _handler(s)
    rid = uuid.uuid4()
    h.on_tool_start({"name": "search"}, "query text", run_id=rid)
    h.on_tool_end("the result", run_id=rid)
    types_seen = _types(t)
    assert "tool_call" in types_seen and "tool_result" in types_seen
    call = [e for e in t.events if e["type"] == "tool_call"][0]["payload"]
    result = [e for e in t.events if e["type"] == "tool_result"][0]["payload"]
    assert call["tool_name"] == "search"
    assert call["call_id"] == str(rid) == result["call_id"]


def test_tool_error_emits_tool_result_with_error(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s4", transport=t)
    h = _handler(s)
    rid = uuid.uuid4()
    h.on_tool_start({"name": "search"}, "q", run_id=rid)
    h.on_tool_error(RuntimeError("kaboom"), run_id=rid)
    result = [e for e in t.events if e["type"] == "tool_result"][0]["payload"]
    assert "kaboom" in (result.get("error") or "")


def test_llm_error_drops_state_no_event(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s5", transport=t)
    h = _handler(s)
    rid = uuid.uuid4()
    h.on_llm_start({"name": "L"}, ["p"], run_id=rid)
    h.on_llm_error(RuntimeError("x"), run_id=rid)
    # No llm_call emitted, and a subsequent on_llm_end for the same run is a no-op popped run.
    assert "llm_call" not in _types(t)


def test_agent_action_emits_agent_message(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s6", transport=t)
    h = _handler(s)
    action = types.SimpleNamespace(log="thinking about it", tool="search")
    h.on_agent_action(action, run_id=uuid.uuid4())
    msgs = [e for e in t.events if e["type"] == "agent_message"]
    assert msgs and "thinking" in msgs[0]["payload"]["content"]


def test_model_falls_back_to_unknown(fake_langchain):
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s7", transport=t)
    h = _handler(s)
    rid = uuid.uuid4()
    h.on_llm_start({}, ["p"], run_id=rid)  # no model anywhere

    class Result:
        llm_output = {}
        generations: list[Any] = []

    h.on_llm_end(Result(), run_id=rid)
    payload = [e for e in t.events if e["type"] == "llm_call"][0]["payload"]
    assert payload["model"] == "unknown"
