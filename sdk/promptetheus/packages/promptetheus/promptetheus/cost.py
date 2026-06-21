"""Token and cost accounting for Promptetheus.

This module turns LLM token usage into approximate USD cost. It ships a small,
overridable price table for common OpenAI and Anthropic models and a couple of
helpers:

- estimate_tokens(text, model) estimates token count, using tiktoken when the
  optional tiktoken extra is installed and a cheap len(text)/4 heuristic
  otherwise. It never raises.
- estimate_cost(model, input_tokens, output_tokens) returns the approximate
  USD cost for one call.
- annotate_cost(event) returns a copy of an llm_call event with an estimated
  cost_usd added to its payload (estimating tokens from text when needed).
- accumulate_session_cost(events) sums cost across the llm_call events of a
  session and returns a small breakdown (SessionCost).
- format_cost(summary) renders a SessionCost as a one-line human summary.
- Budget(limit_usd).check(summary) reports whether a session's spend has crossed
  a USD limit. It is purely advisory: nothing in this module raises or stops a
  run; the caller decides what to do.

IMPORTANT: the prices in DEFAULT_MODEL_PRICES are approximate and change over
time. They are provided as a convenience, not a billing source of truth. Pass a
prices override (a model -> ModelPrice mapping) to estimate_cost /
accumulate_session_cost, or mutate DEFAULT_MODEL_PRICES in your own process, to
use current numbers. Costs are computed as:

    input_tokens / 1000 * input_per_1k + output_tokens / 1000 * output_per_1k

Unknown models contribute 0.0 cost (and are reported separately by the
accumulator) rather than guessing a price.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ModelPrice:
    """USD price per 1,000 tokens for one model.

    input_per_1k is the prompt/input price; output_per_1k is the
    completion/output price. Both are dollars per 1,000 tokens.
    """

    input_per_1k: float
    output_per_1k: float


# Approximate, user-overridable price table (USD per 1,000 tokens). These are
# rough public list prices captured for convenience and WILL drift; treat them
# as a default to override, not a billing source of truth. Keys are lowercased
# model identifiers; lookup also matches by prefix so dated snapshots like
# gpt-4o-2024-08-06 resolve to the gpt-4o entry.
DEFAULT_MODEL_PRICES: dict[str, ModelPrice] = {
    # -- OpenAI --
    "gpt-4o": ModelPrice(0.0025, 0.01),
    "gpt-4o-mini": ModelPrice(0.00015, 0.0006),
    # gpt-4.1 family. Listed explicitly so longest-prefix resolution keeps them
    # off the much pricier gpt-4 entry (gpt-4.1 starts with gpt-4).
    "gpt-4.1": ModelPrice(0.002, 0.008),
    "gpt-4.1-mini": ModelPrice(0.0004, 0.0016),
    "gpt-4.1-nano": ModelPrice(0.0001, 0.0004),
    "gpt-4-turbo": ModelPrice(0.01, 0.03),
    "gpt-4": ModelPrice(0.03, 0.06),
    "gpt-3.5-turbo": ModelPrice(0.0005, 0.0015),
    "o1": ModelPrice(0.015, 0.06),
    "o1-mini": ModelPrice(0.0011, 0.0044),
    "o3": ModelPrice(0.002, 0.008),
    "o3-mini": ModelPrice(0.0011, 0.0044),
    "o4-mini": ModelPrice(0.0011, 0.0044),
    # -- Anthropic --
    "claude-3-5-sonnet": ModelPrice(0.003, 0.015),
    "claude-3-5-haiku": ModelPrice(0.0008, 0.004),
    "claude-3-7-sonnet": ModelPrice(0.003, 0.015),
    "claude-sonnet-4": ModelPrice(0.003, 0.015),
    "claude-opus-4": ModelPrice(0.015, 0.075),
    "claude-haiku-4": ModelPrice(0.001, 0.005),
    "claude-3-opus": ModelPrice(0.015, 0.075),
    "claude-3-sonnet": ModelPrice(0.003, 0.015),
    "claude-3-haiku": ModelPrice(0.00025, 0.00125),
}


def resolve_price(
    model: str | None,
    prices: Mapping[str, ModelPrice] | None = None,
) -> ModelPrice | None:
    """Look up the price for a model, or None when it is unknown.

    Resolution is case-insensitive and tries, in order: an exact match, then the
    longest known key that the model name starts with (so dated snapshots such
    as gpt-4o-2024-08-06 or claude-3-5-sonnet-20241022 resolve to their base
    entry). When prices is given it REPLACES DEFAULT_MODEL_PRICES entirely (pass a
    full table); to extend the defaults instead, merge them yourself
    (prices={**DEFAULT_MODEL_PRICES, "my-model": ...}) or mutate the default table.
    """

    if not model:
        return None

    table = prices if prices is not None else DEFAULT_MODEL_PRICES
    key = model.lower()

    if key in table:
        return table[key]

    # Prefix match: pick the longest known key the model name starts with.
    best: str | None = None
    for candidate in table:
        if key.startswith(candidate) and (best is None or len(candidate) > len(best)):
            best = candidate
    return table[best] if best is not None else None


def estimate_cost(
    model: str | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    *,
    prices: Mapping[str, ModelPrice] | None = None,
) -> float:
    """Estimate the approximate USD cost of one LLM call.

    input_tokens and output_tokens may be None (treated as 0). An unknown model
    returns 0.0 rather than guessing. Prices are approximate and overridable via
    the prices mapping; see the module docstring.
    """

    price = resolve_price(model, prices)
    if price is None:
        return 0.0

    in_tokens = _as_count(input_tokens)
    out_tokens = _as_count(output_tokens)
    return (
        in_tokens / 1000.0 * price.input_per_1k
        + out_tokens / 1000.0 * price.output_per_1k
    )


# Average characters per token for the heuristic fallback. ~4 chars/token is a
# reasonable rule of thumb for English text across common tokenizers; it is only
# used when tiktoken is not installed.
_CHARS_PER_TOKEN = 4.0


@lru_cache(maxsize=64)
def _tiktoken_encoding(model: str | None) -> Any | None:
    """Return a cached tiktoken encoding for model, or None if unavailable.

    tiktoken is an optional dependency (the tiktoken extra). It is imported
    lazily here so importing this module never requires it. When tiktoken is
    absent, or it cannot resolve an encoding for the given model, this returns
    None and callers fall back to the cheap character heuristic. Never raises.
    """

    try:
        import tiktoken
    except Exception:
        return None

    try:
        if model:
            try:
                return tiktoken.encoding_for_model(model)
            except Exception:
                # Unknown model name: fall back to a general-purpose encoding.
                pass
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _heuristic_tokens(text: str) -> int:
    """Cheap, dependency-free token estimate: about one token per four chars.

    Rounds up so any non-empty text counts as at least one token. Used when
    tiktoken is not installed or cannot produce an encoding.
    """

    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN + 0.999))


def estimate_tokens(text: str, model: str | None = None) -> int:
    """Estimate the number of tokens in text.

    Uses tiktoken when it is installed (the tiktoken extra), selecting an
    encoding for model when one is known and otherwise a general-purpose
    encoding. When tiktoken is absent it falls back to a cheap character-count
    heuristic (about len(text) / 4). Non-string or empty input returns 0. This
    function never raises; on any internal failure it falls back to the
    heuristic so instrumentation stays advisory.
    """

    if not isinstance(text, str) or not text:
        return 0

    encoding = _tiktoken_encoding(model)
    if encoding is not None:
        try:
            return len(encoding.encode(text))
        except Exception:
            pass
    return _heuristic_tokens(text)


def annotate_cost(
    event: Mapping[str, Any],
    *,
    prices: Mapping[str, ModelPrice] | None = None,
) -> dict[str, Any]:
    """Return a copy of an llm_call event with an estimated cost_usd in payload.

    Reads model and input_tokens / output_tokens from the event payload and
    writes the approximate USD cost under payload["cost_usd"]. When input_tokens
    or output_tokens are absent but input_text / output_text are present in the
    payload, token counts are estimated with estimate_tokens first (and written
    back as input_tokens / output_tokens). Non-llm_call events and events with an
    unknown model are returned with cost_usd 0.0. The input is never mutated; a
    new dict (with a new payload dict) is returned. Never raises.
    """

    new_event = dict(event)
    payload_in = event.get("payload") if isinstance(event, Mapping) else None
    payload: dict[str, Any] = (
        dict(payload_in) if isinstance(payload_in, Mapping) else {}
    )
    new_event["payload"] = payload

    if not isinstance(event, Mapping) or event.get("type") != "llm_call":
        payload.setdefault("cost_usd", 0.0)
        return new_event

    model = payload.get("model")
    model = model if isinstance(model, str) else None

    in_tokens = payload.get("input_tokens")
    if in_tokens is None and isinstance(payload.get("input_text"), str):
        in_tokens = estimate_tokens(payload["input_text"], model)
        payload["input_tokens"] = in_tokens
    out_tokens = payload.get("output_tokens")
    if out_tokens is None and isinstance(payload.get("output_text"), str):
        out_tokens = estimate_tokens(payload["output_text"], model)
        payload["output_tokens"] = out_tokens

    payload["cost_usd"] = estimate_cost(
        model,
        _as_count(in_tokens),
        _as_count(out_tokens),
        prices=prices,
    )
    return new_event


@dataclass(frozen=True)
class SessionCost:
    """Accumulated cost across the llm_call events of a session.

    total_usd is the summed approximate cost. input_tokens / output_tokens are
    the summed token counts. llm_calls is how many llm_call events were seen.
    priced_calls is how many of those resolved to a known model price; the
    difference (llm_calls - priced_calls) contributed 0.0 cost. unknown_models is
    the sorted set of model names that had no price entry.
    """

    total_usd: float
    input_tokens: int
    output_tokens: int
    llm_calls: int
    priced_calls: int
    unknown_models: tuple[str, ...]


def accumulate_session_cost(
    events: Iterable[Mapping[str, Any]],
    *,
    prices: Mapping[str, ModelPrice] | None = None,
) -> SessionCost:
    """Sum approximate cost and tokens across the llm_call events in events.

    events is any iterable of enveloped events (e.g. what a RecordingTransport
    captured, or a session's buffered timeline). Non-llm_call events are ignored.
    Each llm_call's model and input_tokens / output_tokens are read from its
    payload. Unknown models contribute 0.0 cost and are reported in
    unknown_models. Prices are approximate and overridable via prices.
    """

    total = 0.0
    in_total = 0
    out_total = 0
    llm_calls = 0
    priced_calls = 0
    unknown: set[str] = set()

    for event in events:
        if not isinstance(event, Mapping) or event.get("type") != "llm_call":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, Mapping):
            payload = {}

        llm_calls += 1
        model = payload.get("model")
        in_tokens = _as_count(payload.get("input_tokens"))
        out_tokens = _as_count(payload.get("output_tokens"))
        in_total += in_tokens
        out_total += out_tokens

        price = resolve_price(model if isinstance(model, str) else None, prices)
        if price is None:
            if isinstance(model, str) and model:
                unknown.add(model)
            continue
        priced_calls += 1
        total += estimate_cost(model, in_tokens, out_tokens, prices=prices)

    return SessionCost(
        total_usd=total,
        input_tokens=in_total,
        output_tokens=out_total,
        llm_calls=llm_calls,
        priced_calls=priced_calls,
        unknown_models=tuple(sorted(unknown)),
    )


@dataclass(frozen=True)
class BudgetStatus:
    """Advisory result of checking a SessionCost against a USD limit.

    spent_usd is the session's accumulated cost; limit_usd is the configured
    ceiling. exceeded is True when spent_usd is strictly greater than limit_usd.
    remaining_usd is limit_usd - spent_usd (negative once exceeded). fraction is
    spent_usd / limit_usd (0.0 when limit_usd is 0). This is a pure report for
    the caller to act on; nothing here raises or stops the run.
    """

    spent_usd: float
    limit_usd: float
    exceeded: bool
    remaining_usd: float
    fraction: float


class Budget:
    """A simple advisory USD spend limit for a session.

    Construct with a dollar ceiling and call check(summary) with a SessionCost
    (or anything exposing total_usd) to get a BudgetStatus. This is purely
    advisory: it never raises and never stops instrumentation. The caller decides
    what to do when a budget is exceeded (log, abort their own loop, alert).

        budget = Budget(0.50)
        status = budget.check(accumulate_session_cost(events))
        if status.exceeded:
            ...  # caller acts

    A negative limit is clamped to 0.0.
    """

    def __init__(self, limit_usd: float) -> None:
        try:
            limit = float(limit_usd)
        except (TypeError, ValueError):
            limit = 0.0
        self.limit_usd = limit if limit > 0.0 else 0.0

    def check(self, summary: SessionCost | float) -> BudgetStatus:
        """Report this budget's status against a SessionCost or a raw USD total."""

        if isinstance(summary, SessionCost):
            spent = float(summary.total_usd)
        else:
            try:
                spent = float(summary)
            except (TypeError, ValueError):
                spent = 0.0

        remaining = self.limit_usd - spent
        fraction = spent / self.limit_usd if self.limit_usd > 0.0 else 0.0
        return BudgetStatus(
            spent_usd=spent,
            limit_usd=self.limit_usd,
            exceeded=spent > self.limit_usd,
            remaining_usd=remaining,
            fraction=fraction,
        )

    def exceeded(self, summary: SessionCost | float) -> bool:
        """Convenience: True when summary's spend is over this budget's limit."""

        return self.check(summary).exceeded


def format_cost(summary: SessionCost) -> str:
    """Return a one-line human summary of a SessionCost.

    Example: $0.0135 across 2 LLM call(s), 3000 in / 2000 out tokens. When some
    calls had no known price, an unpriced note is appended.
    """

    parts = [
        f"${summary.total_usd:.4f} across {summary.llm_calls} LLM call(s)",
        f"{summary.input_tokens} in / {summary.output_tokens} out tokens",
    ]
    unpriced = summary.llm_calls - summary.priced_calls
    if unpriced > 0:
        models = (
            ", ".join(summary.unknown_models) if summary.unknown_models else "unknown"
        )
        parts.append(f"{unpriced} unpriced ({models})")
    return "; ".join(parts)


def _as_count(value: Any) -> int:
    """Coerce a token-count value to a non-negative int (0 on anything odd).

    bool is rejected (it is an int subclass but never a real token count).
    """

    if value is None or isinstance(value, bool):
        return 0
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return count if count > 0 else 0


__all__ = [
    "DEFAULT_MODEL_PRICES",
    "Budget",
    "BudgetStatus",
    "ModelPrice",
    "SessionCost",
    "accumulate_session_cost",
    "annotate_cost",
    "estimate_cost",
    "estimate_tokens",
    "format_cost",
    "resolve_price",
]
