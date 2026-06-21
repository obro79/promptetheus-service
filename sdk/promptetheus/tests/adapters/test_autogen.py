"""Tests for the AutoGen adapter.

AutoGen (autogen-agentchat / pyautogen) is NOT installed in this environment,
so this adapter is REVIEW-VERIFIED, not lib-verified: the ConversableAgent
register_reply hook protocol and the message shapes exercised below were
checked against AutoGen's documented contract and the fakes here mirror those
shapes:

- The fake agent mimics ConversableAgent's register_reply(trigger, reply_func):
  it stores the reply func and exposes reply() which invokes the stored hook as
  reply_func(recipient, messages=..., sender=..., config=...) and asserts the
  hook returns (False, None) — i.e. it observes without intercepting.
- The fake messages carry AutoGen's real field names: assistant turns use
  role/content plus tool_calls ({id, function: {name, arguments}}); tool
  responses use role "tool" with tool_call_id + content.

The first layer asserts the import-safety + lazy-error contract (must hold with
AutoGen absent); the second drives the adapter against the fake agent and
asserts it stays thin (only public event types) and non-intrusive.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any

import pytest

from promptetheus.session import Session

_HAS_AUTOGEN = (
    importlib.util.find_spec("autogen") is not None
    or importlib.util.find_spec("pyautogen") is not None
    or importlib.util.find_spec("ag2") is not None
)

# Event types the AutoGen adapter is permitted to emit. Anything outside this set
# means the adapter grew an adapter-only event type ("adapters stay thin").
PUBLIC_ADAPTER_EVENT_TYPES = {
    "llm_call",
    "tool_call",
    "tool_result",
    "agent_message",
}


class RecordingTransport:
    """In-memory transport capturing every enveloped event the session emits."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flushed = False

    def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def flush(self, timeout: float | None = None) -> None:
        self.flushed = True


def _events_of(transport: RecordingTransport, event_type: str) -> list[dict[str, Any]]:
    return [e for e in transport.events if e["type"] == event_type]


# -- import-safety + lazy-export contract (holds regardless of the extra) -----


def test_module_imports_without_autogen() -> None:
    """Importing the adapter module must not require autogen installed."""
    module = importlib.import_module("promptetheus.adapters.autogen")
    assert hasattr(module, "AutoGenAdapter")


def test_lazy_export_is_callable() -> None:
    """AutoGenAdapter is lazily exported from promptetheus.adapters and callable."""
    from promptetheus.adapters import AutoGenAdapter

    assert callable(AutoGenAdapter)


@pytest.mark.skipif(
    _HAS_AUTOGEN,
    reason="autogen installed; this asserts the missing-dependency error path",
)
def test_calling_without_autogen_raises_clear_error() -> None:
    """Constructing the adapter without autogen raises a clear RuntimeError."""
    from promptetheus.adapters import AutoGenAdapter

    with pytest.raises(RuntimeError, match="autogen"):
        AutoGenAdapter()


@pytest.mark.skipif(
    _HAS_AUTOGEN,
    reason="autogen installed; this asserts the missing-dependency error path",
)
def test_error_fires_before_session_work_with_explicit_session() -> None:
    """The lazy error fires at construction, before any telemetry is emitted."""
    from promptetheus.adapters import AutoGenAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)

    with pytest.raises(RuntimeError, match="autogen"):
        AutoGenAdapter(session)
    assert transport.events == []


# -- fakes mirroring the documented AutoGen agent + message shapes ------------


class _FakeConversableAgent:
    """Mirror of AutoGen ConversableAgent's register_reply surface.

    Stores reply funcs registered via register_reply(trigger, reply_func) and
    exposes reply(messages, sender) which invokes each stored hook exactly as
    AutoGen does — reply_func(self, messages=..., sender=..., config=...) — and
    records the (final, reply) tuple it returned so a test can assert the hook
    observed without intercepting.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._reply_funcs: list[Any] = []
        self.last_results: list[Any] = []

    def register_reply(self, trigger: Any, reply_func: Any, *args: Any, **kwargs: Any) -> None:
        self._reply_funcs.append(reply_func)

    def reply(self, messages: list[dict[str, Any]], sender: Any = None) -> None:
        self.last_results = [
            func(self, messages=messages, sender=sender, config=None)
            for func in self._reply_funcs
        ]


def _install_fake_autogen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make promptetheus.adapters.autogen resolve our fake ConversableAgent.

    Patches _require_autogen so the adapter constructs without the real library,
    exactly as it would resolve the real ConversableAgent class when installed.
    """
    module = importlib.import_module("promptetheus.adapters.autogen")
    monkeypatch.setattr(module, "_require_autogen", lambda: _FakeConversableAgent)


@pytest.fixture()
def adapter_factory(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Return a builder for AutoGenAdapter wired to the fake ConversableAgent."""
    _install_fake_autogen(monkeypatch)
    from promptetheus.adapters import AutoGenAdapter

    def _build(session: Session) -> Any:
        return AutoGenAdapter(session)

    return _build


# -- driving the adapter against the fake agent -------------------------------


def test_attach_observes_text_turn_as_agent_message(adapter_factory: Any) -> None:
    """A plain text reply turn maps to a single agent_message, non-intrusively."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = adapter_factory(session)

    agent = _FakeConversableAgent("assistant")
    adapter.attach(agent)

    agent.reply([{"role": "assistant", "content": "I can help with that."}])

    # The hook never intercepts: it returns (False, None) so AutoGen continues.
    assert agent.last_results == [(False, None)]

    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    messages = _events_of(transport, "agent_message")
    assert len(messages) == 1
    assert messages[0]["payload"]["content"] == "I can help with that."


def test_tool_call_turn_maps_to_tool_call(adapter_factory: Any) -> None:
    """An assistant turn carrying tool_calls maps to one tool_call per call."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = adapter_factory(session)

    agent = _FakeConversableAgent("assistant")
    adapter.attach(agent)

    agent.reply(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "search_rooms",
                            "arguments": '{"city": "paris"}',
                        },
                    }
                ],
            }
        ]
    )

    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    tool_calls = _events_of(transport, "tool_call")
    assert len(tool_calls) == 1
    payload = tool_calls[0]["payload"]
    assert payload["tool_name"] == "search_rooms"
    assert payload["arguments"] == {"city": "paris"}
    assert payload["call_id"] == "call_1"

    # content was None, so no agent_message for this tool-only turn.
    assert _events_of(transport, "agent_message") == []


def test_tool_response_turn_maps_to_tool_result(adapter_factory: Any) -> None:
    """A role=tool turn maps to tool_result correlated by tool_call_id."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = adapter_factory(session)

    agent = _FakeConversableAgent("user_proxy")
    adapter.attach(agent)

    # First the assistant requests the tool, then the tool turn returns output.
    agent.reply(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "search_rooms", "arguments": "{}"}}
                ],
            }
        ]
    )
    agent.reply(
        [
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "found 3 rooms",
            }
        ]
    )

    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    tool_calls = _events_of(transport, "tool_call")
    tool_results = _events_of(transport, "tool_result")
    assert len(tool_calls) == 1
    assert len(tool_results) == 1
    assert tool_calls[0]["payload"]["call_id"] == "call_1"
    assert tool_results[0]["payload"]["call_id"] == "call_1"
    assert tool_results[0]["payload"]["result"] == "found 3 rooms"


def test_legacy_function_call_shape(adapter_factory: Any) -> None:
    """The older single function_call dict is still mapped to a tool_call."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = adapter_factory(session)

    agent = _FakeConversableAgent("assistant")
    adapter.attach(agent)

    agent.reply(
        [
            {
                "role": "assistant",
                "content": "",
                "function_call": {"name": "lookup", "arguments": '{"q": "x"}'},
            }
        ]
    )

    tool_calls = _events_of(transport, "tool_call")
    assert len(tool_calls) == 1
    assert tool_calls[0]["payload"]["tool_name"] == "lookup"
    assert tool_calls[0]["payload"]["arguments"] == {"q": "x"}


def test_detach_all_silences_further_observation(adapter_factory: Any) -> None:
    """After detach_all the hook stays installed but emits nothing further."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = adapter_factory(session)

    agent = _FakeConversableAgent("assistant")
    adapter.attach(agent)
    adapter.detach_all()

    agent.reply([{"role": "assistant", "content": "should not be recorded"}])

    # The hook still returns (False, None) (never intrusive) but emitted nothing.
    assert agent.last_results == [(False, None)]
    assert transport.events == []


def test_context_manager_silences_on_exit(adapter_factory: Any) -> None:
    """Using the adapter as a context manager stops observation on exit."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)

    importlib.import_module("promptetheus.adapters.autogen")
    from promptetheus.adapters import AutoGenAdapter

    agent = _FakeConversableAgent("assistant")
    with AutoGenAdapter(session) as adapter:
        adapter.attach(agent)
        agent.reply([{"role": "assistant", "content": "inside"}])

    assert len(_events_of(transport, "agent_message")) == 1

    # After exit, further turns emit nothing.
    agent.reply([{"role": "assistant", "content": "after"}])
    assert len(_events_of(transport, "agent_message")) == 1


def test_trigger_is_always_true_callable_not_none(adapter_factory: Any) -> None:
    """attach registers an always-true callable trigger, never trigger=None.

    AutoGen's _match_trigger treats trigger=None as "matches only when sender is
    None", which would silence the hook for normal agent-to-agent turns. The
    adapter must register a Callable[[Agent], bool] trigger that returns True for
    every sender so the hook fires on every turn.
    """
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = adapter_factory(session)

    recorded: list[Any] = []

    class _TriggerRecordingAgent(_FakeConversableAgent):
        def register_reply(
            self, trigger: Any, reply_func: Any, *args: Any, **kwargs: Any
        ) -> None:
            recorded.append(trigger)
            super().register_reply(trigger, reply_func, *args, **kwargs)

    agent = _TriggerRecordingAgent("assistant")
    adapter.attach(agent)

    assert len(recorded) == 1
    trigger = recorded[0]
    assert trigger is not None
    assert callable(trigger)
    # Fires for a non-None sender (a normal agent-to-agent turn).
    assert trigger(object()) is True
    assert trigger(None) is True


def test_hook_fires_for_non_none_sender(adapter_factory: Any) -> None:
    """The hook still emits when the sender is another (non-None) agent.

    Proves the always-true trigger semantics: a normal agent-to-agent reply turn
    (sender is the other agent, not None) is observed and emitted.
    """
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = adapter_factory(session)

    agent = _FakeConversableAgent("assistant")
    other = _FakeConversableAgent("user_proxy")
    adapter.attach(agent)

    agent.reply([{"role": "assistant", "content": "from a real turn"}], sender=other)

    messages = _events_of(transport, "agent_message")
    assert len(messages) == 1
    assert messages[0]["payload"]["content"] == "from a real turn"


def test_shared_message_emits_once_across_two_attached_agents(adapter_factory: Any) -> None:
    """A turn observed by two attached agents' hooks emits exactly once.

    AutoGen shares the running message list across the conversation, so the same
    latest message can be seen by more than one attached agent's hook. The
    per-adapter seen-set must de-duplicate so the turn yields a single
    agent_message, not one per attached agent.
    """
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = adapter_factory(session)

    assistant = _FakeConversableAgent("assistant")
    user_proxy = _FakeConversableAgent("user_proxy")
    adapter.attach(assistant)
    adapter.attach(user_proxy)

    # One shared message list observed by both agents' hooks.
    shared = [{"role": "assistant", "content": "one logical turn"}]
    assistant.reply(shared)
    user_proxy.reply(shared)

    messages = _events_of(transport, "agent_message")
    assert len(messages) == 1
    assert messages[0]["payload"]["content"] == "one logical turn"


def test_attach_skips_agent_without_register_reply(adapter_factory: Any) -> None:
    """Attaching to an object lacking register_reply is a no-op, never raises."""
    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    adapter = adapter_factory(session)

    class _NoHookAgent:
        name = "plain"

    adapter.attach(_NoHookAgent())  # must not raise
    assert transport.events == []
