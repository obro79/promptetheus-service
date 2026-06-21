"""Tests for token/cost accounting (promptetheus.cost).

These exercise estimate_cost (price lookup, prefix matching, unknown models,
overrides) and accumulate_session_cost (summing across the llm_call events of a
recorded session). No network, no provider libraries.
"""

from __future__ import annotations

import math
from importlib.util import find_spec

import pytest

from promptetheus.cost import (
    DEFAULT_MODEL_PRICES,
    Budget,
    BudgetStatus,
    ModelPrice,
    SessionCost,
    accumulate_session_cost,
    annotate_cost,
    estimate_cost,
    estimate_tokens,
    format_cost,
    resolve_price,
)

_HAS_TIKTOKEN = find_spec("tiktoken") is not None


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


# -- estimate_cost ---------------------------------------------------------


def test_estimate_cost_known_model_matches_table() -> None:
    # gpt-4o: 0.0025 / 1k input, 0.01 / 1k output.
    cost = estimate_cost("gpt-4o", 1000, 1000)
    assert _close(cost, 0.0025 + 0.01)


def test_estimate_cost_scales_with_tokens() -> None:
    cost = estimate_cost("gpt-4o-mini", 2000, 500)
    expected = 2000 / 1000 * 0.00015 + 500 / 1000 * 0.0006
    assert _close(cost, expected)


def test_estimate_cost_unknown_model_is_zero() -> None:
    assert estimate_cost("some-random-model", 1000, 1000) == 0.0


def test_estimate_cost_none_tokens_treated_as_zero() -> None:
    assert estimate_cost("gpt-4o", None, None) == 0.0
    # Only output present.
    assert _close(estimate_cost("gpt-4o", None, 1000), 0.01)


def test_estimate_cost_prefix_match_for_dated_snapshot() -> None:
    # Dated snapshot ids should resolve to their base entry by prefix.
    base = estimate_cost("gpt-4o", 1000, 1000)
    dated = estimate_cost("gpt-4o-2024-08-06", 1000, 1000)
    assert _close(base, dated)

    anthropic_dated = estimate_cost("claude-3-5-sonnet-20241022", 1000, 0)
    assert _close(anthropic_dated, 0.003)


def test_estimate_cost_is_case_insensitive() -> None:
    assert _close(estimate_cost("GPT-4O", 1000, 0), estimate_cost("gpt-4o", 1000, 0))


def test_estimate_cost_override_prices() -> None:
    prices = {"my-model": ModelPrice(input_per_1k=1.0, output_per_1k=2.0)}
    cost = estimate_cost("my-model", 1000, 1000, prices=prices)
    assert _close(cost, 3.0)
    # The override table replaces the default, so a default model is unknown here.
    assert estimate_cost("gpt-4o", 1000, 1000, prices=prices) == 0.0


def test_resolve_price_unknown_returns_none() -> None:
    assert resolve_price("nope-not-a-model") is None
    assert resolve_price(None) is None
    assert resolve_price("") is None


def test_default_table_covers_both_providers() -> None:
    assert "gpt-4o" in DEFAULT_MODEL_PRICES
    assert "claude-3-5-sonnet" in DEFAULT_MODEL_PRICES


# -- accumulate_session_cost ----------------------------------------------


def _llm_call(model: str, input_tokens: int, output_tokens: int) -> dict:
    return {
        "type": "llm_call",
        "payload": {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


def test_accumulate_sums_cost_and_tokens_across_calls() -> None:
    events = [
        {"type": "user_message", "payload": {"content": "hi"}},
        _llm_call("gpt-4o", 1000, 1000),
        _llm_call("gpt-4o-mini", 2000, 1000),
        {"type": "session_end", "payload": {"status": "completed"}},
    ]

    result = accumulate_session_cost(events)
    assert isinstance(result, SessionCost)

    expected = (0.0025 + 0.01) + (2000 / 1000 * 0.00015 + 1000 / 1000 * 0.0006)
    assert _close(result.total_usd, expected)
    assert result.input_tokens == 3000
    assert result.output_tokens == 2000
    assert result.llm_calls == 2
    assert result.priced_calls == 2
    assert result.unknown_models == ()


def test_accumulate_reports_unknown_models_with_zero_cost() -> None:
    events = [
        _llm_call("gpt-4o", 1000, 0),
        _llm_call("mystery-model-x", 5000, 5000),
    ]

    result = accumulate_session_cost(events)
    # Only the gpt-4o call contributes cost.
    assert _close(result.total_usd, 0.0025)
    # Tokens are still summed for the unknown model.
    assert result.input_tokens == 6000
    assert result.output_tokens == 5000
    assert result.llm_calls == 2
    assert result.priced_calls == 1
    assert result.unknown_models == ("mystery-model-x",)


def test_accumulate_ignores_non_llm_events() -> None:
    events = [
        {"type": "agent_message", "payload": {"content": "thinking"}},
        {"type": "tool_call", "payload": {"tool_name": "x", "arguments": {}}},
    ]
    result = accumulate_session_cost(events)
    assert result.total_usd == 0.0
    assert result.llm_calls == 0
    assert result.input_tokens == 0


def test_accumulate_tolerates_missing_token_fields() -> None:
    events = [{"type": "llm_call", "payload": {"model": "gpt-4o"}}]
    result = accumulate_session_cost(events)
    assert result.total_usd == 0.0
    assert result.llm_calls == 1
    assert result.priced_calls == 1
    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_accumulate_with_price_override() -> None:
    prices = {"house-model": ModelPrice(0.001, 0.002)}
    events = [_llm_call("house-model", 1000, 1000)]
    result = accumulate_session_cost(events, prices=prices)
    assert _close(result.total_usd, 0.003)
    assert result.priced_calls == 1
    assert result.unknown_models == ()


# -- estimate_tokens -------------------------------------------------------


def test_estimate_tokens_empty_and_non_string_are_zero() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0  # type: ignore[arg-type]
    assert estimate_tokens(123) == 0  # type: ignore[arg-type]


def test_estimate_tokens_is_positive_for_text() -> None:
    # Whatever path is taken, a non-trivial string must yield a positive count.
    assert estimate_tokens("hello world, this is a sentence") > 0


def test_estimate_tokens_roughly_scales_with_length() -> None:
    short = estimate_tokens("a")
    longer = estimate_tokens("a" * 400)
    assert longer > short


@pytest.mark.skipif(_HAS_TIKTOKEN, reason="exercises the no-tiktoken heuristic path")
def test_estimate_tokens_heuristic_without_tiktoken() -> None:
    # ~len/4, rounded up. 40 chars -> 10 tokens.
    assert estimate_tokens("x" * 40) == 10
    # Short non-empty text is at least one token.
    assert estimate_tokens("hi") == 1


@pytest.mark.skipif(not _HAS_TIKTOKEN, reason="requires the tiktoken extra")
def test_estimate_tokens_with_tiktoken() -> None:
    import tiktoken

    text = "The quick brown fox jumps over the lazy dog."
    enc = tiktoken.get_encoding("cl100k_base")
    assert estimate_tokens(text) == len(enc.encode(text))


def test_estimate_tokens_never_raises_on_odd_model() -> None:
    # An unknown model name must still produce a count, not an error.
    assert estimate_tokens("some text", model="not-a-real-model-xyz") > 0


# -- annotate_cost ---------------------------------------------------------


def test_annotate_cost_adds_cost_usd_to_llm_call() -> None:
    event = _llm_call("gpt-4o", 1000, 1000)
    annotated = annotate_cost(event)
    assert _close(annotated["payload"]["cost_usd"], 0.0025 + 0.01)
    # Original event is not mutated.
    assert "cost_usd" not in event["payload"]


def test_annotate_cost_estimates_tokens_from_text() -> None:
    event = {
        "type": "llm_call",
        "payload": {"model": "gpt-4o", "input_text": "x" * 40, "output_text": "y" * 40},
    }
    annotated = annotate_cost(event)
    payload = annotated["payload"]
    assert payload["input_tokens"] == estimate_tokens("x" * 40, "gpt-4o")
    assert payload["output_tokens"] == estimate_tokens("y" * 40, "gpt-4o")
    assert payload["cost_usd"] > 0.0


def test_annotate_cost_unknown_model_is_zero() -> None:
    annotated = annotate_cost(_llm_call("mystery-model", 1000, 1000))
    assert annotated["payload"]["cost_usd"] == 0.0


def test_annotate_cost_non_llm_event_is_zero() -> None:
    annotated = annotate_cost({"type": "user_message", "payload": {"content": "hi"}})
    assert annotated["payload"]["cost_usd"] == 0.0


# -- Budget ----------------------------------------------------------------


def _summary(total_usd: float) -> SessionCost:
    return SessionCost(
        total_usd=total_usd,
        input_tokens=0,
        output_tokens=0,
        llm_calls=1,
        priced_calls=1,
        unknown_models=(),
    )


def test_budget_under_limit_not_exceeded() -> None:
    budget = Budget(1.0)
    status = budget.check(_summary(0.25))
    assert isinstance(status, BudgetStatus)
    assert status.exceeded is False
    assert _close(status.remaining_usd, 0.75)
    assert _close(status.fraction, 0.25)
    assert budget.exceeded(_summary(0.25)) is False


def test_budget_over_limit_exceeded() -> None:
    budget = Budget(0.50)
    status = budget.check(_summary(0.75))
    assert status.exceeded is True
    assert _close(status.remaining_usd, -0.25)
    assert status.fraction > 1.0
    assert budget.exceeded(_summary(0.75)) is True


def test_budget_accepts_raw_total() -> None:
    assert Budget(1.0).check(2.0).exceeded is True
    assert Budget(1.0).check(0.5).exceeded is False


def test_budget_negative_limit_clamped_to_zero() -> None:
    budget = Budget(-5.0)
    assert budget.limit_usd == 0.0
    # With a zero limit, any positive spend is over.
    assert budget.check(_summary(0.01)).exceeded is True
    assert budget.check(_summary(0.0)).exceeded is False
    # No division by zero in fraction.
    assert budget.check(_summary(0.01)).fraction == 0.0


def test_budget_does_not_raise_on_bad_input() -> None:
    budget = Budget(1.0)
    # A non-numeric total is treated as 0.0 spend, never raises.
    assert budget.check("not a number").exceeded is False  # type: ignore[arg-type]


# -- format_cost -----------------------------------------------------------


def test_format_cost_one_line_summary() -> None:
    events = [_llm_call("gpt-4o", 1000, 1000), _llm_call("gpt-4o-mini", 2000, 1000)]
    summary = accumulate_session_cost(events)
    line = format_cost(summary)
    assert "\n" not in line
    assert "2 LLM call(s)" in line
    assert "3000 in / 2000 out tokens" in line
    assert line.startswith("$")


def test_format_cost_notes_unpriced_calls() -> None:
    events = [_llm_call("gpt-4o", 1000, 0), _llm_call("mystery-model-x", 100, 100)]
    summary = accumulate_session_cost(events)
    line = format_cost(summary)
    assert "1 unpriced" in line
    assert "mystery-model-x" in line
