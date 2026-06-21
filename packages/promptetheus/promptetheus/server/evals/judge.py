"""LLM-as-judge scorer.

Mirrors `verifier.critique_fix`'s Claude call shape exactly
(`client.messages.parse(..., output_format=Model)` -> `.parsed_output`) so the
same fake-Anthropic test seam works here. Given an assertion the answer must
satisfy plus the evidence/context, it returns whether a candidate answer
satisfies the assertion. The runner — not the judge — owns the
deterministic-fallback decision; the judge just scores or raises.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from promptetheus.server.evals.dataset import EvalCase

_MODEL = os.environ.get("PROMPTETHEUS_EVAL_MODEL", "claude-opus-4-8")


class _EvalOut(BaseModel):
    satisfies: bool = Field(description="True only if the candidate answer satisfies the assertion.")
    confidence: float = Field(description="0.0-1.0 confidence in the verdict.")
    reason: str = Field(description="One or two sentences justifying the verdict.")


_SYSTEM = (
    "You are a strict evaluator of an AI agent's answer. You are given an assertion "
    "the answer MUST satisfy, the evidence/context the agent had, and a candidate "
    "answer. Decide ONLY whether the candidate answer satisfies the assertion. An "
    "answer that contradicts the retrieved evidence does NOT satisfy it. Be "
    "conservative: when unsure, it does not satisfy."
)


def judge_output(case: EvalCase, candidate: str) -> _EvalOut:
    """Score one candidate answer against the case assertion. May raise."""

    import anthropic

    prompt = "\n".join(
        [
            "## Assertion the answer must satisfy",
            case.assertion,
            "",
            "## Evidence / context",
            case.context,
            "",
            "## Candidate answer",
            (candidate or "(empty)")[:8000],
            "",
            "Does the candidate answer satisfy the assertion? Return your verdict.",
        ]
    )
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=_MODEL,
        max_tokens=2000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=_EvalOut,
    )
    parsed: _EvalOut = response.parsed_output
    return parsed


def judge_available() -> bool:
    """True when a real judge call can be made (key + anthropic importable)."""

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False
    return True


__all__ = ["judge_output", "judge_available", "_EvalOut"]
