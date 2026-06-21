#!/usr/bin/env python3
"""Minimal LangChain callback example — produces a Promptetheus session."""

from __future__ import annotations

import sys
import types
import uuid


def _install_fake_langchain() -> None:
    class BaseCallbackHandler:
        def __init__(self, *args, **kwargs):
            pass

    root = types.ModuleType("langchain_core")
    callbacks = types.ModuleType("langchain_core.callbacks")
    callbacks.BaseCallbackHandler = BaseCallbackHandler
    root.callbacks = callbacks
    sys.modules["langchain_core"] = root
    sys.modules["langchain_core.callbacks"] = callbacks


def main() -> None:
    _install_fake_langchain()

    from promptetheus.adapters.langchain import PromptetheusCallbackHandler
    from promptetheus.trace import start

    transport_events: list[dict] = []

    class CaptureTransport:
        def create_trace(self, metadata):
            pass

        def send_event(self, event):
            transport_events.append(dict(event))

        def flush(self, timeout=None):
            pass

    transport = CaptureTransport()
    with start(agent="langchain-demo", user_goal="Summarize the doc", transport=transport) as session:
        handler = PromptetheusCallbackHandler(session)
        run_id = uuid.uuid4()
        handler.on_llm_start({"name": "FakeLLM"}, ["hello"], run_id=run_id)

        class Result:
            llm_output = {"token_usage": {"prompt_tokens": 3, "completion_tokens": 2}}
            generations: list = []

        handler.on_llm_end(Result(), run_id=run_id)
        session_id = session.session_id

    types_seen = {event["type"] for event in transport_events}
    print("session_id:", session_id)
    print("event_types:", sorted(types_seen))
    assert "llm_call" in types_seen
    assert "session_end" in types_seen


if __name__ == "__main__":
    main()
