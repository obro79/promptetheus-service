"""Tests for the Pydantic-AI adapter.

Pydantic-AI is NOT installed in this environment, so this adapter is
REVIEW-VERIFIED, not lib-verified: the Agent.run/run_sync surface, the
message-history shape, and the message-part fields exercised below were checked
against the Pydantic-AI docs and source (pydantic_ai.agent and
pydantic_ai.messages), and the fakes here mirror those real shapes:

- A run result exposes all_messages() returning an ordered list of
  ModelRequest / ModelResponse objects.
- A ModelResponse carries parts (TextPart with content, ToolCallPart with
  tool_name / args / tool_call_id) and a usage block (request_tokens /
  response_tokens) plus model_name.
- A ModelRequest carries the tool outputs fed back to the model: ToolReturnPart
  (tool_name / content / tool_call_id) and RetryPromptPart (tool_name /
  content / tool_call_id) for tool errors.
- Each part carries a part_kind discriminator ("text", "tool-call",
  "tool-return", "retry-prompt").

The first layer asserts the import-safety + lazy-error contract (it holds
regardless of whether the extra is installed); the second drives the adapter
against a fake agent whose run_sync returns a fake result mirroring the shapes
above.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.session import Session  # noqa: E402

_HAS_PYDANTIC_AI = importlib.util.find_spec("pydantic_ai") is not None

# Event types the Pydantic-AI adapter is permitted to emit. Anything outside
# this set means the adapter grew an adapter-only event type ("adapters stay
# thin").
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


# -- import-safety + lazy-export contract (holds regardless of the extra) ----


def test_module_imports_without_pydantic_ai() -> None:
    importlib.import_module("promptetheus.adapters.pydantic_ai")


def test_lazy_export_is_callable() -> None:
    from promptetheus.adapters import PydanticAIAdapter

    assert callable(PydanticAIAdapter)


@pytest.mark.skipif(
    _HAS_PYDANTIC_AI,
    reason="pydantic_ai installed; this asserts the missing-dependency error path",
)
def test_constructing_without_pydantic_ai_raises_clear_error() -> None:
    from promptetheus.adapters import PydanticAIAdapter

    with pytest.raises(RuntimeError, match="pydantic-ai"):
        PydanticAIAdapter(object())


# -- fakes mirroring the real Pydantic-AI message shapes (review-verified) ---


class _Part:
    """Base fake message part: stores arbitrary fields as attributes."""

    part_kind = ""

    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


class TextPart(_Part):
    """Mirror of pydantic_ai TextPart (content)."""

    part_kind = "text"


class ToolCallPart(_Part):
    """Mirror of pydantic_ai ToolCallPart (tool_name / args / tool_call_id)."""

    part_kind = "tool-call"


class ToolReturnPart(_Part):
    """Mirror of pydantic_ai ToolReturnPart (tool_name / content / tool_call_id)."""

    part_kind = "tool-return"


class RetryPromptPart(_Part):
    """Mirror of pydantic_ai RetryPromptPart (tool_name / content / tool_call_id)."""

    part_kind = "retry-prompt"


class _Usage:
    """Mirror of pydantic_ai Usage (request_tokens / response_tokens)."""

    def __init__(self, request_tokens: int | None, response_tokens: int | None) -> None:
        self.request_tokens = request_tokens
        self.response_tokens = response_tokens


class ModelRequest:
    """Mirror of pydantic_ai ModelRequest (carries tool-return parts)."""

    def __init__(self, parts: list[Any]) -> None:
        self.parts = parts


class ModelResponse:
    """Mirror of pydantic_ai ModelResponse (parts + usage + model_name)."""

    def __init__(self, parts: list[Any], model_name: str, usage: _Usage) -> None:
        self.parts = parts
        self.model_name = model_name
        self.usage = usage


class _Result:
    """Mirror of a pydantic_ai run result exposing all_messages()."""

    def __init__(self, messages: list[Any]) -> None:
        self._messages = messages

    def all_messages(self) -> list[Any]:
        return self._messages


class _FakeAgent:
    """Fake pydantic_ai Agent whose run_sync returns a canned result."""

    def __init__(self, result: _Result) -> None:
        self._result = result
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        # An attribute the adapter should pass through unchanged.
        self.model = "fake-model"

    def run_sync(self, *args: Any, **kwargs: Any) -> _Result:
        self.calls.append((args, kwargs))
        return self._result


@pytest.fixture()
def fake_pydantic_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a minimal pydantic_ai module so the import gate passes.

    The adapter never references pydantic_ai symbols (it duck-types the agent
    and messages); it only imports the module to fail clearly when the extra is
    absent. A bare module is enough to satisfy that gate.
    """
    import types

    monkeypatch.setitem(sys.modules, "pydantic_ai", types.ModuleType("pydantic_ai"))


def _build_result() -> _Result:
    """A two-turn run: model calls a tool, tool returns, model answers."""
    first_response = ModelResponse(
        parts=[
            TextPart(content="Let me look that up."),
            ToolCallPart(
                tool_name="search",
                args={"q": "rooms"},
                tool_call_id="call_1",
            ),
        ],
        model_name="gpt-4o",
        usage=_Usage(request_tokens=11, response_tokens=7),
    )
    tool_return_request = ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name="search",
                content="found 3 rooms",
                tool_call_id="call_1",
            ),
        ],
    )
    final_response = ModelResponse(
        parts=[TextPart(content="There are 3 rooms available.")],
        model_name="gpt-4o",
        usage=_Usage(request_tokens=20, response_tokens=9),
    )
    return _Result([first_response, tool_return_request, final_response])


# -- driving the adapter against the fake agent -----------------------------


def test_run_sync_emits_public_correlated_events(fake_pydantic_ai: None) -> None:
    """A full run drives only public, correlated Session events."""
    from promptetheus.adapters import PydanticAIAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    agent = _FakeAgent(_build_result())
    adapter = PydanticAIAdapter(agent, session)

    result = adapter.run_sync("Find me a room", deps="x")

    # The real result is returned unchanged and the agent saw our arguments.
    assert isinstance(result, _Result)
    assert agent.calls == [(("Find me a room",), {"deps": "x"})]

    # Only public event types.
    emitted_types = {e["type"] for e in transport.events}
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES, emitted_types

    # Two model responses -> two llm_call events with model + mapped usage.
    llm_calls = _events_of(transport, "llm_call")
    assert len(llm_calls) == 2
    assert llm_calls[0]["payload"]["model"] == "gpt-4o"
    assert llm_calls[0]["payload"]["input_tokens"] == 11
    assert llm_calls[0]["payload"]["output_tokens"] == 7
    assert llm_calls[1]["payload"]["input_tokens"] == 20
    assert llm_calls[1]["payload"]["output_tokens"] == 9

    # Text parts -> agent_message.
    agent_messages = _events_of(transport, "agent_message")
    assert [m["payload"]["content"] for m in agent_messages] == [
        "Let me look that up.",
        "There are 3 rooms available.",
    ]

    # tool_call and tool_result correlate via Pydantic-AI's tool_call_id.
    tool_calls = _events_of(transport, "tool_call")
    tool_results = _events_of(transport, "tool_result")
    assert len(tool_calls) == 1
    assert len(tool_results) == 1
    assert tool_calls[0]["payload"]["tool_name"] == "search"
    assert tool_calls[0]["payload"]["arguments"] == {"q": "rooms"}
    call_id = tool_calls[0]["payload"]["call_id"]
    assert call_id == "call_1"
    assert call_id == tool_results[0]["payload"]["call_id"]
    assert tool_results[0]["payload"]["result"] == "found 3 rooms"


def test_tool_args_json_string_is_parsed(fake_pydantic_ai: None) -> None:
    """A ToolCallPart whose args are a JSON string is parsed into a dict."""
    from promptetheus.adapters import PydanticAIAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    response = ModelResponse(
        parts=[
            ToolCallPart(
                tool_name="search",
                args='{"q": "rooms"}',
                tool_call_id="call_9",
            ),
        ],
        model_name="gpt-4o",
        usage=_Usage(request_tokens=1, response_tokens=1),
    )
    adapter = PydanticAIAdapter(_FakeAgent(_Result([response])), session)

    adapter.run_sync("x")

    tool_calls = _events_of(transport, "tool_call")
    assert len(tool_calls) == 1
    assert tool_calls[0]["payload"]["arguments"] == {"q": "rooms"}


def test_retry_prompt_maps_to_tool_result_error(fake_pydantic_ai: None) -> None:
    """A RetryPromptPart naming a tool maps to tool_result(error=...)."""
    from promptetheus.adapters import PydanticAIAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)
    response = ModelResponse(
        parts=[
            ToolCallPart(tool_name="search", args={}, tool_call_id="call_2"),
        ],
        model_name="gpt-4o",
        usage=_Usage(request_tokens=2, response_tokens=2),
    )
    retry_request = ModelRequest(
        parts=[
            RetryPromptPart(
                tool_name="search",
                content="invalid arguments",
                tool_call_id="call_2",
            ),
        ],
    )
    adapter = PydanticAIAdapter(
        _FakeAgent(_Result([response, retry_request])), session
    )

    adapter.run_sync("x")

    tool_results = _events_of(transport, "tool_result")
    assert len(tool_results) == 1
    assert tool_results[0]["payload"]["call_id"] == "call_2"
    assert tool_results[0]["payload"]["error"] == "invalid arguments"
    assert tool_results[0]["payload"]["result"] is None


def test_run_sync_never_raises_on_malformed_result(fake_pydantic_ai: None) -> None:
    """A result with no usable message history emits nothing and never raises."""
    from promptetheus.adapters import PydanticAIAdapter

    transport = RecordingTransport()
    session = Session(agent="agent", user_goal="goal", transport=transport)

    class _BadResult:
        def all_messages(self) -> list[Any]:
            raise RuntimeError("boom")

    adapter = PydanticAIAdapter(_FakeAgent(_BadResult()), session)  # type: ignore[arg-type]

    # The real result is still returned; instrumentation failure is swallowed.
    result = adapter.run_sync("x")
    assert isinstance(result, _BadResult)
    assert transport.events == []


def test_unknown_attribute_passes_through_to_agent(fake_pydantic_ai: None) -> None:
    """Attributes the adapter does not instrument delegate to the wrapped agent."""
    from promptetheus.adapters import PydanticAIAdapter

    session = Session(agent="agent", user_goal="goal")
    agent = _FakeAgent(_Result([]))
    adapter = PydanticAIAdapter(agent, session)

    assert adapter.model == "fake-model"


def test_defaults_to_current_session(fake_pydantic_ai: None) -> None:
    """With no explicit session the adapter records into the active session."""
    from promptetheus.adapters import PydanticAIAdapter

    transport = RecordingTransport()
    response = ModelResponse(
        parts=[TextPart(content="hi")],
        model_name="gpt-4o",
        usage=_Usage(request_tokens=1, response_tokens=1),
    )

    with Session(agent="agent", user_goal="goal", transport=transport):
        adapter = PydanticAIAdapter(_FakeAgent(_Result([response])))
        adapter.run_sync("x")

    assert len(_events_of(transport, "agent_message")) == 1
