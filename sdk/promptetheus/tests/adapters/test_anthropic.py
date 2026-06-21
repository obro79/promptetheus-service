"""Tests for the Anthropic adapter.

These tests run with NO anthropic package installed. They prove the adapter
stays *thin* over the public Session API and never depends on the real
provider library:

- create is a faithful pass-through: it returns the real client response
  unchanged;
- it emits exactly one llm_call carrying model plus the token usage and
  measured latency_ms (and NO raw prompt/message content);
- it emits one agent_message per text content block;
- it emits one tool_call per tool_use block with the right
  tool_name / arguments / call_id;
- across a run it emits only standard event types — no adapter-only types;
- importing promptetheus.adapters.anthropic does not require anthropic.

The adapter instruments a *passed-in* client (duck-typed), so we drive it with a
tiny fake Anthropic client. anthropic is never imported here.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from promptetheus.session import Session


# The only event types the Anthropic adapter is permitted to emit. Anything
# outside this set means the adapter grew an adapter-only event type, which
# violates "adapters stay thin".
PUBLIC_ADAPTER_EVENT_TYPES = {"llm_call", "agent_message", "tool_call"}

# Fields that would leak raw prompt/message content into the event stream. The
# adapter must never put any of these into an llm_call payload — it records
# token usage and model identity, optionally a *_ref, never content.
FORBIDDEN_LLM_CALL_PAYLOAD_KEYS = {
    "messages",
    "prompt",
    "content",
    "system",
    "input",
    "text",
}


# ---------------------------------------------------------------------------
# Fake Anthropic client (duck-typed; no real anthropic import)
# ---------------------------------------------------------------------------


class FakeUsage:
    """Stub for response.usage — only needs the two token counts."""

    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeTextBlock:
    """A text content block: .type == 'text' with a .text string."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class FakeToolUseBlock:
    """A tool_use content block: .type / .name / .input / .id."""

    def __init__(self, name: str, input: dict[str, Any], id: str) -> None:
        self.type = "tool_use"
        self.name = name
        self.input = input
        self.id = id


class FakeMessage:
    """A fake Anthropic Message response.

    Carries .model, .usage (input/output tokens), and .content (the
    ordered list of content blocks) — the exact surface the adapter reads.
    """

    def __init__(
        self,
        model: str,
        usage: FakeUsage | None,
        content: list[Any],
    ) -> None:
        self.model = model
        self.usage = usage
        self.content = content


class FakeMessages:
    """Stub for client.messages — records the kwargs create was called with."""

    def __init__(self, response: FakeMessage) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeMessage:
        self.calls.append(kwargs)
        return self._response


class FakeAnthropicClient:
    """Duck-typed stand-in for anthropic.Anthropic — only .messages.create."""

    def __init__(self, response: FakeMessage) -> None:
        self.messages = FakeMessages(response)


class RecordingTransport:
    """In-memory transport that captures every enveloped event the session emits."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flushed = False

    def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def flush(self, timeout: float | None = None) -> None:
        self.flushed = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _default_response() -> FakeMessage:
    """A realistic mixed response: one text block + one tool_use block + usage."""
    return FakeMessage(
        model="claude-3-5-sonnet-20241022",
        usage=FakeUsage(input_tokens=37, output_tokens=12),
        content=[
            FakeTextBlock("Booking Tuesday at 2:00 PM Pacific."),
            FakeToolUseBlock(
                name="book_meeting",
                input={"day": "tuesday", "time": "14:00", "tz": "America/Los_Angeles"},
                id="toolu_abc123",
            ),
        ],
    )


@pytest.fixture
def make_adapter():
    """Build an AnthropicAdapter over a real Session + RecordingTransport.

    Returns (adapter, client, transport). Imported here (not at module top)
    so the adapter import path is exercised inside the test.
    """
    from promptetheus.adapters.anthropic import AnthropicAdapter

    def _make(response: FakeMessage | None = None, **session_kwargs: Any):
        response = response if response is not None else _default_response()
        client = FakeAnthropicClient(response)
        transport = RecordingTransport()
        session = Session(
            agent="booking-agent",
            user_goal="Book Tuesday at 2pm Pacific",
            transport=transport,
            **session_kwargs,
        )
        adapter = AnthropicAdapter(client, session)
        return adapter, client, transport

    return _make


def _events(transport: RecordingTransport, type_: str) -> list[dict[str, Any]]:
    return [e for e in transport.events if e["type"] == type_]


# ---------------------------------------------------------------------------
# Import safety: no top-level anthropic dependency
# ---------------------------------------------------------------------------


def test_adapter_module_imports_without_anthropic(monkeypatch: pytest.MonkeyPatch):
    """Importing the adapter module must not require anthropic.

    We assert anthropic is genuinely absent, force a fresh import of the
    adapter module, and confirm it imports and exposes AnthropicAdapter.
    """
    import importlib

    # Ensure no anthropic is resolvable, and force a fresh import of the adapter.
    monkeypatch.delitem(sys.modules, "anthropic", raising=False)
    monkeypatch.delitem(sys.modules, "promptetheus.adapters.anthropic", raising=False)

    assert importlib.util.find_spec("anthropic") is None

    module = importlib.import_module("promptetheus.adapters.anthropic")
    assert hasattr(module, "AnthropicAdapter")


def test_adapter_constructs_without_anthropic_installed(make_adapter):
    """Constructing + using the adapter never imports the real anthropic.

    The fake client is duck-typed; if the adapter tried to import anthropic
    to function this run would fail (it is not installed).
    """
    assert "anthropic" not in sys.modules
    adapter, client, transport = make_adapter()
    adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=1024, messages=[])
    assert "anthropic" not in sys.modules


# ---------------------------------------------------------------------------
# Pass-through: real response returned unchanged, real call driven
# ---------------------------------------------------------------------------


def test_create_returns_the_real_response_and_drives_the_client(make_adapter):
    response = _default_response()
    adapter, client, transport = make_adapter(response)

    result = adapter.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Book Tuesday at 2pm"}],
    )

    # The exact provider response object is returned, untouched.
    assert result is response
    # The wrapped client's create was actually invoked, with the caller kwargs.
    assert len(client.messages.calls) == 1
    assert client.messages.calls[0]["model"] == "claude-3-5-sonnet-20241022"
    assert client.messages.calls[0]["max_tokens"] == 1024


# ---------------------------------------------------------------------------
# llm_call: model + token usage + latency, and NO raw content
# ---------------------------------------------------------------------------


def test_emits_one_llm_call_with_model_usage_and_latency(make_adapter):
    response = FakeMessage(
        model="claude-3-5-sonnet-20241022",
        usage=FakeUsage(input_tokens=37, output_tokens=12),
        content=[FakeTextBlock("ok")],
    )
    adapter, client, transport = make_adapter(response)

    adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=64, messages=[])

    calls = _events(transport, "llm_call")
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload["model"] == "claude-3-5-sonnet-20241022"
    assert payload["input_tokens"] == 37
    assert payload["output_tokens"] == 12
    # latency is measured around the call: present, a non-bool int, >= 0.
    assert "latency_ms" in payload
    assert isinstance(payload["latency_ms"], int)
    assert not isinstance(payload["latency_ms"], bool)
    assert payload["latency_ms"] >= 0


def test_llm_call_carries_no_raw_prompt_or_message_content(make_adapter):
    """The llm_call payload must not leak prompts/messages/content.

    Content references (messages_ref / prompt_ref) are allowed; raw
    content is not. We also confirm the actual message text we passed in is
    nowhere in the payload.
    """
    secret_prompt = "TOP-SECRET-USER-PROMPT-Book Tuesday at 2pm"
    adapter, client, transport = make_adapter()

    adapter.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        system="you are a careful booking agent",
        messages=[{"role": "user", "content": secret_prompt}],
    )

    payload = _events(transport, "llm_call")[0]["payload"]
    # No content-bearing keys.
    assert FORBIDDEN_LLM_CALL_PAYLOAD_KEYS.isdisjoint(payload.keys())
    # And the literal prompt text never appears anywhere in the serialized payload.
    assert secret_prompt not in repr(payload)


# ---------------------------------------------------------------------------
# content blocks: text -> agent_message, tool_use -> tool_call
# ---------------------------------------------------------------------------


def test_text_blocks_emit_agent_messages(make_adapter):
    response = FakeMessage(
        model="claude-3-5-sonnet-20241022",
        usage=FakeUsage(5, 6),
        content=[
            FakeTextBlock("First, I'll check availability."),
            FakeTextBlock("Then I'll confirm the booking."),
        ],
    )
    adapter, client, transport = make_adapter(response)

    adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=128, messages=[])

    messages = _events(transport, "agent_message")
    assert [m["payload"]["content"] for m in messages] == [
        "First, I'll check availability.",
        "Then I'll confirm the booking.",
    ]


def test_tool_use_block_emits_tool_call_with_correct_fields(make_adapter):
    response = FakeMessage(
        model="claude-3-5-sonnet-20241022",
        usage=FakeUsage(5, 6),
        content=[
            FakeToolUseBlock(
                name="book_meeting",
                input={"day": "tuesday", "time": "14:00"},
                id="toolu_xyz789",
            ),
        ],
    )
    adapter, client, transport = make_adapter(response)

    adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=128, messages=[])

    tool_calls = _events(transport, "tool_call")
    assert len(tool_calls) == 1
    payload = tool_calls[0]["payload"]
    assert payload["tool_name"] == "book_meeting"
    assert payload["arguments"] == {"day": "tuesday", "time": "14:00"}
    assert payload["call_id"] == "toolu_xyz789"


def test_mixed_content_emits_message_then_tool_call_in_order(make_adapter):
    """A mixed text + tool_use response emits both, preserving block order."""
    adapter, client, transport = make_adapter()  # default mixed response

    adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=1024, messages=[])

    # Across the run: 1 llm_call, 1 agent_message, 1 tool_call.
    assert len(_events(transport, "llm_call")) == 1
    assert len(_events(transport, "agent_message")) == 1
    assert len(_events(transport, "tool_call")) == 1

    # The agent_message precedes the tool_call (content-block order preserved).
    non_llm = [e for e in transport.events if e["type"] != "llm_call"]
    assert [e["type"] for e in non_llm] == ["agent_message", "tool_call"]


# ---------------------------------------------------------------------------
# Thinness: across a full run, only the standard event types are emitted
# ---------------------------------------------------------------------------


def test_full_run_emits_only_standard_event_types(make_adapter):
    adapter, client, transport = make_adapter()  # default: text + tool_use + usage

    adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=1024, messages=[])

    emitted_types = {e["type"] for e in transport.events}
    # No adapter-only event types.
    assert emitted_types <= PUBLIC_ADAPTER_EVENT_TYPES
    # All three standard categories were exercised.
    assert emitted_types == PUBLIC_ADAPTER_EVENT_TYPES


def test_adapter_emits_no_session_lifecycle_events(make_adapter):
    """The adapter itself never emits session lifecycle / unrelated events.

    The Session is constructed directly (not entered as a context manager), so
    the only events present must come from the adapter's create call.
    """
    adapter, client, transport = make_adapter()

    adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=1024, messages=[])

    for event in transport.events:
        assert event["type"] not in {
            "state_change",
            "session_end",
            "user_message",
            "tool_result",
            "browser_action",
        }


# ---------------------------------------------------------------------------
# Streaming: stream=True yields a wrapper that emits one llm_call after the
# stream completes, capturing ttft + usage + the streamed text.
# ---------------------------------------------------------------------------
#
# Fake Anthropic stream events mirror the real shapes the adapter reads:
# - message_start: .message.model + .message.usage.input_tokens
# - content_block_delta: .delta.text
# - message_delta: .usage.output_tokens


class FakeStreamUsage:
    def __init__(self, input_tokens: int | None = None, output_tokens: int | None = None) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeStartMessage:
    def __init__(self, model: str, usage: FakeStreamUsage) -> None:
        self.model = model
        self.usage = usage


class FakeMessageStart:
    def __init__(self, model: str, input_tokens: int) -> None:
        self.type = "message_start"
        self.message = FakeStartMessage(model, FakeStreamUsage(input_tokens=input_tokens, output_tokens=0))


class FakeTextDelta:
    def __init__(self, text: str) -> None:
        self.type = "text_delta"
        self.text = text


class FakeContentBlockDelta:
    def __init__(self, text: str) -> None:
        self.type = "content_block_delta"
        self.delta = FakeTextDelta(text)


class FakeMessageDelta:
    def __init__(self, output_tokens: int) -> None:
        self.type = "message_delta"
        self.usage = FakeStreamUsage(output_tokens=output_tokens)


class FakeMessageStop:
    def __init__(self) -> None:
        self.type = "message_stop"


class FakeStreamingMessages:
    """client.messages.create(stream=True) returns an iterator of events."""

    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return iter(self._events)


class FakeStreamingClient:
    def __init__(self, events: list[Any]) -> None:
        self.messages = FakeStreamingMessages(events)


def _stream_events() -> list[Any]:
    return [
        FakeMessageStart("claude-3-5-sonnet-20241022", input_tokens=42),
        FakeContentBlockDelta("Booking "),
        FakeContentBlockDelta("Tuesday "),
        FakeContentBlockDelta("at 2pm."),
        FakeMessageDelta(output_tokens=9),
        FakeMessageStop(),
    ]


def _stream_adapter(events: list[Any] | None = None):
    """Build an AnthropicAdapter over a streaming fake client + RecordingTransport."""
    from promptetheus.adapters.anthropic import AnthropicAdapter

    events = events if events is not None else _stream_events()
    client = FakeStreamingClient(events)
    transport = RecordingTransport()
    session = Session(
        agent="booking-agent",
        user_goal="Book Tuesday at 2pm Pacific",
        transport=transport,
    )
    adapter = AnthropicAdapter(client, session)
    return adapter, client, transport


def test_streaming_yields_events_unchanged():
    events = _stream_events()
    adapter, client, transport = _stream_adapter(events)

    stream = adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=64, messages=[], stream=True)
    seen = list(stream)

    assert seen == events
    # The wrapped client was actually driven with stream=True.
    assert client.messages.calls[0]["stream"] is True


def test_streaming_emits_one_llm_call_after_completion():
    adapter, client, transport = _stream_adapter()

    stream = adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=64, messages=[], stream=True)

    # No llm_call before the stream is drained.
    next(iter(stream))
    assert len(_events(transport, "llm_call")) == 0

    for _ in stream:
        pass

    calls = _events(transport, "llm_call")
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload["model"] == "claude-3-5-sonnet-20241022"
    assert payload["input_tokens"] == 42
    assert payload["output_tokens"] == 9
    assert "latency_ms" in payload


def test_streaming_metadata_carries_streamed_and_ttft():
    adapter, client, transport = _stream_adapter()

    list(adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=64, messages=[], stream=True))

    metadata = _events(transport, "llm_call")[0].get("metadata", {})
    assert metadata.get("streamed") is True
    assert "ttft_ms" in metadata
    assert isinstance(metadata["ttft_ms"], int)
    assert metadata["ttft_ms"] >= 0


def test_streaming_emits_concatenated_agent_message():
    adapter, client, transport = _stream_adapter()

    list(adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=64, messages=[], stream=True))

    messages = _events(transport, "agent_message")
    assert len(messages) == 1
    assert messages[0]["payload"]["content"] == "Booking Tuesday at 2pm."


def test_streaming_emits_only_standard_event_types():
    adapter, client, transport = _stream_adapter()

    list(adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=64, messages=[], stream=True))

    emitted = {e["type"] for e in transport.events}
    assert emitted <= PUBLIC_ADAPTER_EVENT_TYPES


def test_streaming_without_usage_still_emits_llm_call():
    events = [
        FakeContentBlockDelta("a"),
        FakeContentBlockDelta("b"),
        FakeMessageStop(),
    ]
    adapter, client, transport = _stream_adapter(events)

    list(adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=64, messages=[], stream=True))

    calls = _events(transport, "llm_call")
    assert len(calls) == 1
    payload = calls[0]["payload"]
    # No message_start, so model falls back; usage omitted.
    assert "input_tokens" not in payload
    assert "output_tokens" not in payload
    # The streamed text still produced an agent_message.
    assert _events(transport, "agent_message")[0]["payload"]["content"] == "ab"


def test_non_streaming_path_unaffected_by_stream_support(make_adapter):
    """A plain create (stream omitted) still behaves exactly as before."""
    adapter, client, transport = make_adapter()

    result = adapter.create(model="claude-3-5-sonnet-20241022", max_tokens=1024, messages=[])

    # Standard non-streaming emission: llm_call without streamed metadata.
    payload = _events(transport, "llm_call")[0]["payload"]
    metadata = payload.get("metadata")
    assert metadata is None or "streamed" not in metadata
