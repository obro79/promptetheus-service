"""Tests for the OpenAI adapter.

These tests run with NO real network and NO openai package installed. They
prove the adapter stays *thin* over the public Session API:

- wrapping client.chat.completions.create returns the *real* response object
  unchanged;
- each completion emits exactly one llm_call carrying model plus the
  token/latency fields the provider reports (input_tokens/output_tokens/
  latency_ms);
- one tool_call is emitted per tool call in the response, with the function
  name and parsed arguments;
- across a whole run the adapter emits NO event types outside the standard set;
- raw prompt/message content is never placed in the llm_call payload;
- importing promptetheus.adapters.openai does not require openai.

The adapter is duck-typed over a user-supplied client and never imports
openai, so a hand-rolled fake client is sufficient to exercise it.
"""

from __future__ import annotations

import json
from typing import Any

from promptetheus.adapters.openai import OpenAIAdapter
from promptetheus.session import Session


# Event types the OpenAI adapter is permitted to emit. Anything outside this set
# means the adapter grew an adapter-only event type, which violates "adapters
# stay thin".
PUBLIC_ADAPTER_EVENT_TYPES = {
    "llm_call",
    "tool_call",
    "tool_result",
    "agent_message",
    "user_message",
    "retrieval",
}

# Envelope/control event types the Session itself emits around a run. These are
# not produced by the adapter and are filtered out before adapter assertions.
SESSION_LIFECYCLE_EVENT_TYPES = {"state_change", "session_end"}


class RecordingTransport:
    """In-memory transport that captures every enveloped event the session emits."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flushed = False

    def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def flush(self, timeout: float | None = None) -> None:
        self.flushed = True


# -- fake OpenAI client ----------------------------------------------------
#
# A minimal stand-in for openai.OpenAI. It mirrors the attribute shape the
# adapter duck-types against: client.chat.completions.create(**kwargs)
# returning a response with .model, .usage (.prompt_tokens /
# .completion_tokens) and .choices[0].message (.content and an
# optional .tool_calls list, each entry with .id and .function).


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[FakeToolCall] | None = None,
    ) -> None:
        self.role = "assistant"
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message: FakeMessage) -> None:
        self.index = 0
        self.message = message
        self.finish_reason = "stop"


class FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class FakeResponse:
    def __init__(
        self,
        model: str,
        message: FakeMessage,
        usage: FakeUsage | None = None,
    ) -> None:
        self.id = "chatcmpl-fake"
        self.model = model
        self.choices = [FakeChoice(message)]
        self.usage = usage


class FakeCompletions:
    """Records the kwargs it was called with and returns a pre-baked response."""

    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.last_kwargs: dict[str, Any] | None = None
        self.call_count = 0

    def create(self, **kwargs: Any) -> FakeResponse:
        self.call_count += 1
        self.last_kwargs = kwargs
        return self._response


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeClient:
    """Stand-in for openai.OpenAI — only the surface the adapter touches."""

    def __init__(self, response: FakeResponse) -> None:
        self.completions = FakeCompletions(response)
        self.chat = FakeChat(self.completions)


# -- helpers ---------------------------------------------------------------


def _session(transport: RecordingTransport) -> Session:
    return Session(
        agent="test-agent",
        user_goal="exercise the openai adapter",
        transport=transport,
    )


def _adapter_events(transport: RecordingTransport) -> list[dict[str, Any]]:
    """Events emitted by the adapter (session lifecycle events filtered out)."""
    return [
        event
        for event in transport.events
        if event["type"] not in SESSION_LIFECYCLE_EVENT_TYPES
    ]


def _of_type(events: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [event for event in events if event["type"] == event_type]


# -- tests -----------------------------------------------------------------


def test_import_without_openai_installed() -> None:
    """Importing the adapter module must not require openai to be installed."""
    import importlib
    import sys

    assert "openai" not in sys.modules, "test precondition: openai must be absent"

    module = importlib.import_module("promptetheus.adapters.openai")
    assert hasattr(module, "OpenAIAdapter")
    # Still absent after import — the adapter must not import openai at load time.
    assert "openai" not in sys.modules


def test_create_returns_real_response_and_emits_llm_call() -> None:
    """The wrapped create returns the real response and emits one llm_call."""
    response = FakeResponse(
        model="gpt-4o",
        message=FakeMessage(content="Hello there."),
        usage=FakeUsage(prompt_tokens=11, completion_tokens=7),
    )
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeClient(response), session)
        returned = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "secret prompt text"}],
        )

    # The real response object passes through untouched.
    assert returned is response

    events = _adapter_events(transport)
    llm_calls = _of_type(events, "llm_call")
    assert len(llm_calls) == 1

    payload = llm_calls[0]["payload"]
    assert payload["model"] == "gpt-4o"
    assert payload["input_tokens"] == 11
    assert payload["output_tokens"] == 7
    assert "latency_ms" in payload
    assert isinstance(payload["latency_ms"], int)
    assert payload["latency_ms"] >= 0


def test_raw_prompt_content_not_in_llm_call_payload() -> None:
    """Raw prompt/message content must never reach the llm_call payload."""
    secret = "TOP-SECRET-PROMPT-BODY-9f3a"
    response = FakeResponse(
        model="gpt-4o",
        message=FakeMessage(content="ok"),
        usage=FakeUsage(prompt_tokens=3, completion_tokens=1),
    )
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeClient(response), session)
        client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": secret}],
        )

    llm_call = _of_type(_adapter_events(transport), "llm_call")[0]
    serialized = json.dumps(llm_call["payload"])
    assert secret not in serialized
    # No ref was configured, so messages_ref/prompt_ref must be absent entirely.
    assert "messages_ref" not in llm_call["payload"]
    assert "prompt_ref" not in llm_call["payload"]


def test_tool_calls_emit_one_tool_call_each() -> None:
    """Each tool call in the response yields exactly one tool_call event."""
    tool_calls = [
        FakeToolCall(
            "call_a",
            "get_weather",
            json.dumps({"city": "Paris"}),
        ),
        FakeToolCall(
            "call_b",
            "send_email",
            json.dumps({"to": "a@b.com", "subject": "hi"}),
        ),
    ]
    response = FakeResponse(
        model="gpt-4o-mini",
        message=FakeMessage(content=None, tool_calls=tool_calls),
        usage=FakeUsage(prompt_tokens=20, completion_tokens=14),
    )
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeClient(response), session)
        client.chat.completions.create(model="gpt-4o-mini", messages=[])

    events = _adapter_events(transport)
    emitted_tool_calls = _of_type(events, "tool_call")
    assert len(emitted_tool_calls) == 2

    first = emitted_tool_calls[0]["payload"]
    assert first["tool_name"] == "get_weather"
    assert first["arguments"] == {"city": "Paris"}
    assert first["call_id"] == "call_a"

    second = emitted_tool_calls[1]["payload"]
    assert second["tool_name"] == "send_email"
    assert second["arguments"] == {"to": "a@b.com", "subject": "hi"}
    assert second["call_id"] == "call_b"

    # Exactly one llm_call alongside the two tool_calls.
    assert len(_of_type(events, "llm_call")) == 1


def test_only_standard_event_types_emitted() -> None:
    """Across a full run the adapter emits NO event types outside the standard set."""
    response = FakeResponse(
        model="gpt-4o",
        message=FakeMessage(
            content="Done.",
            tool_calls=[FakeToolCall("call_x", "noop", "{}")],
        ),
        usage=FakeUsage(prompt_tokens=5, completion_tokens=2),
    )
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeClient(response), session)
        client.chat.completions.create(model="gpt-4o", messages=[])

    adapter_event_types = {event["type"] for event in _adapter_events(transport)}
    assert adapter_event_types
    assert adapter_event_types <= PUBLIC_ADAPTER_EVENT_TYPES, (
        f"adapter emitted non-standard event types: "
        f"{adapter_event_types - PUBLIC_ADAPTER_EVENT_TYPES}"
    )


def test_response_without_usage_omits_token_counts() -> None:
    """A response with no usage block emits llm_call without token fields."""
    response = FakeResponse(
        model="gpt-4o",
        message=FakeMessage(content="streamed-ish"),
        usage=None,
    )
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeClient(response), session)
        client.chat.completions.create(model="gpt-4o", messages=[])

    payload = _of_type(_adapter_events(transport), "llm_call")[0]["payload"]
    assert payload["model"] == "gpt-4o"
    assert "input_tokens" not in payload
    assert "output_tokens" not in payload
    # Latency is always measurable even without usage.
    assert "latency_ms" in payload


# -- streaming -------------------------------------------------------------
#
# Fake streaming chunks mirror the OpenAI streaming shape the adapter reads:
# chunk.model, chunk.choices[0].delta.content (a text fragment), and a final
# chunk that carries usage (.prompt_tokens / .completion_tokens) when the caller
# requested stream_options={"include_usage": True}.


class FakeDelta:
    def __init__(self, content: str | None = None) -> None:
        self.content = content
        self.role = "assistant"


class FakeStreamChoice:
    def __init__(self, delta: FakeDelta) -> None:
        self.index = 0
        self.delta = delta
        self.finish_reason = None


class FakeChunk:
    def __init__(
        self,
        model: str = "gpt-4o",
        content: str | None = None,
        usage: FakeUsage | None = None,
    ) -> None:
        self.id = "chatcmpl-fake-chunk"
        self.model = model
        self.choices = [FakeStreamChoice(FakeDelta(content))]
        self.usage = usage


class FakeStreamingCompletions:
    """chat.completions.create(stream=True) returns an iterator of chunks."""

    def __init__(self, chunks: list[FakeChunk]) -> None:
        self._chunks = chunks
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        # The provider returns a fresh iterator over the chunks.
        return iter(self._chunks)


class FakeStreamingChat:
    def __init__(self, completions: FakeStreamingCompletions) -> None:
        self.completions = completions


class FakeStreamingClient:
    def __init__(self, chunks: list[FakeChunk]) -> None:
        self.completions = FakeStreamingCompletions(chunks)
        self.chat = FakeStreamingChat(self.completions)


def _streaming_chunks() -> list[FakeChunk]:
    return [
        FakeChunk(content="Hello"),
        FakeChunk(content=", "),
        FakeChunk(content="world."),
        # Final usage-only chunk (no text delta).
        FakeChunk(content=None, usage=FakeUsage(prompt_tokens=13, completion_tokens=5)),
    ]


def test_streaming_yields_chunks_unchanged() -> None:
    """The streaming wrapper yields the provider's chunks unchanged."""
    chunks = _streaming_chunks()
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeStreamingClient(chunks), session)
        stream = client.chat.completions.create(model="gpt-4o", messages=[], stream=True)
        seen = list(stream)

    # Same chunk objects, same order — the wrapper is transparent.
    assert seen == chunks


def test_streaming_emits_one_llm_call_after_completion() -> None:
    """Iterating a stream to completion emits exactly one llm_call."""
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeStreamingClient(_streaming_chunks()), session)
        stream = client.chat.completions.create(model="gpt-4o", messages=[], stream=True)

        # No llm_call should exist mid-stream, before iteration completes.
        first = next(iter(stream))
        assert first is not None
        assert len(_of_type(_adapter_events(transport), "llm_call")) == 0

        # Drain the rest.
        for _ in stream:
            pass

    llm_calls = _of_type(_adapter_events(transport), "llm_call")
    assert len(llm_calls) == 1

    payload = llm_calls[0]["payload"]
    assert payload["model"] == "gpt-4o"
    # Usage from the final chunk is captured.
    assert payload["input_tokens"] == 13
    assert payload["output_tokens"] == 5
    assert "latency_ms" in payload


def test_streaming_metadata_carries_streamed_and_ttft() -> None:
    """The streamed llm_call carries streamed=True and a ttft_ms in metadata."""
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeStreamingClient(_streaming_chunks()), session)
        stream = client.chat.completions.create(model="gpt-4o", messages=[], stream=True)
        list(stream)

    llm_call = _of_type(_adapter_events(transport), "llm_call")[0]
    metadata = llm_call.get("metadata", {})
    assert metadata.get("streamed") is True
    assert "ttft_ms" in metadata
    assert isinstance(metadata["ttft_ms"], int)
    assert metadata["ttft_ms"] >= 0


def test_streaming_emits_concatenated_agent_message() -> None:
    """The streamed text fragments are joined into one agent_message."""
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeStreamingClient(_streaming_chunks()), session)
        stream = client.chat.completions.create(model="gpt-4o", messages=[], stream=True)
        list(stream)

    messages = _of_type(_adapter_events(transport), "agent_message")
    assert len(messages) == 1
    assert messages[0]["payload"]["content"] == "Hello, world."


def test_streaming_emits_only_standard_event_types() -> None:
    """A streamed run emits no event types outside the standard set."""
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeStreamingClient(_streaming_chunks()), session)
        list(client.chat.completions.create(model="gpt-4o", messages=[], stream=True))

    adapter_event_types = {event["type"] for event in _adapter_events(transport)}
    assert adapter_event_types <= PUBLIC_ADAPTER_EVENT_TYPES


def test_streaming_without_usage_still_emits_llm_call() -> None:
    """A stream that never reports usage still emits a single llm_call."""
    chunks = [FakeChunk(content="a"), FakeChunk(content="b")]
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeStreamingClient(chunks), session)
        list(client.chat.completions.create(model="gpt-4o", messages=[], stream=True))

    llm_calls = _of_type(_adapter_events(transport), "llm_call")
    assert len(llm_calls) == 1
    payload = llm_calls[0]["payload"]
    assert payload["model"] == "gpt-4o"
    assert "input_tokens" not in payload
    assert "output_tokens" not in payload


def test_non_streaming_path_unaffected_by_stream_support() -> None:
    """A plain (stream omitted/False) create still behaves exactly as before."""
    response = FakeResponse(
        model="gpt-4o",
        message=FakeMessage(content="hi"),
        usage=FakeUsage(prompt_tokens=4, completion_tokens=2),
    )
    transport = RecordingTransport()

    with _session(transport) as session:
        client = OpenAIAdapter(FakeClient(response), session)
        returned = client.chat.completions.create(model="gpt-4o", messages=[], stream=False)

    assert returned is response
    payload = _of_type(_adapter_events(transport), "llm_call")[0]["payload"]
    assert payload["input_tokens"] == 4
    assert payload["output_tokens"] == 2
    assert payload.get("metadata") is None or "streamed" not in payload.get("metadata", {})
