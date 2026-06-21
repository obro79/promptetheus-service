"""Streaming OpenAI completions feed real token usage into cost accounting.

The OpenAI client is installed but not called over the network here: a fake
client returns a streamed sequence of chunks (content deltas then a usage chunk),
which the adapter folds into one llm_call. We then prove the streamed usage flows
through accumulate_session_cost at the correct (gpt-4.1) price.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.adapters.openai import OpenAIAdapter  # noqa: E402
from promptetheus.cost import accumulate_session_cost, resolve_price  # noqa: E402
from promptetheus.session import Session  # noqa: E402


class RecordingTransport:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def send_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def flush(self, timeout: float | None = None) -> None:
        pass


def _chunk(content=None, model="gpt-4.1", usage=None):
    delta = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(delta=delta)
    return types.SimpleNamespace(model=model, choices=[choice], usage=usage)


class _FakeCompletions:
    def __init__(self, chunks):
        self._chunks = chunks

    def create(self, *args, **kwargs):
        # Streaming: return an iterator of chunks (the adapter wraps it).
        return iter(self._chunks)


class _FakeChat:
    def __init__(self, chunks):
        self.completions = _FakeCompletions(chunks)


class _FakeClient:
    def __init__(self, chunks):
        self.chat = _FakeChat(chunks)


def test_streaming_usage_flows_to_llm_call_and_cost():
    usage = types.SimpleNamespace(prompt_tokens=1000, completion_tokens=2000)
    chunks = [
        _chunk(content="Hello "),
        _chunk(content="world"),
        _chunk(content=None, usage=usage),  # final usage chunk
    ]
    t = RecordingTransport()
    s = Session(agent="a", user_goal="g", session_id="s1", transport=t)
    adapter = OpenAIAdapter(_FakeClient(chunks), session=s)

    stream = adapter.chat.completions.create(model="gpt-4.1", messages=[], stream=True)
    collected = [c for c in stream]  # caller iterates normally
    assert len(collected) == 3  # chunks pass through unchanged

    calls = [e for e in t.events if e["type"] == "llm_call"]
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload["model"] == "gpt-4.1"
    assert payload["input_tokens"] == 1000 and payload["output_tokens"] == 2000
    assert calls[0]["metadata"]["streamed"] is True

    # Assembled streamed text is emitted as an agent_message.
    msgs = [e for e in t.events if e["type"] == "agent_message"]
    assert msgs and msgs[0]["payload"]["content"] == "Hello world"

    # The streamed usage is picked up by the cost accumulator at the gpt-4.1 price.
    summary = accumulate_session_cost(t.events)
    assert summary.llm_calls == 1 and summary.priced_calls == 1
    assert summary.input_tokens == 1000 and summary.output_tokens == 2000
    # gpt-4.1 = 0.002 in / 0.008 out per 1k -> 1*0.002 + 2*0.008 = 0.018
    assert abs(summary.total_usd - 0.018) < 1e-9


def test_gpt_41_no_longer_prices_as_gpt_4():
    # Regression: gpt-4.1 starts with gpt-4 and used to inherit the pricier gpt-4
    # entry via prefix match. It now resolves to its own, cheaper entry.
    p41 = resolve_price("gpt-4.1")
    p4 = resolve_price("gpt-4")
    assert p41 is not None and p4 is not None
    assert p41.input_per_1k < p4.input_per_1k
    # dated snapshots still resolve to the gpt-4.1 base entry
    assert resolve_price("gpt-4.1-2025-04-14") == p41


def test_current_models_are_priced():
    for model in ("claude-sonnet-4", "claude-opus-4", "gpt-4.1-mini", "o3"):
        assert resolve_price(model) is not None, model
