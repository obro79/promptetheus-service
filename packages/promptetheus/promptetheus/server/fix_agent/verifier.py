"""Verification layer for the self-healing loop.

A fix is only allowed to open a PR when it passes BOTH gates:

1. **LLM self-critique** — a second Claude pass (the "judge") that checks the diff
   actually addresses the detected root cause. This is the meaningful gate in
   State-0 (see #2). If Claude isn't wired (no `ANTHROPIC_API_KEY`), the critique
   is skipped/approved so the deterministic demo still closes the loop; if a key
   IS present but the call errors, the critique fails closed (never silently
   approves).
2. **Regression re-run** — reuses `regression.runner.run_regression`. Pass when
   `after_fail == 0`. State-0 regression is a deterministic fallback that always
   passes, so the critique is the load-bearing gate today; both halves are wired
   identically so the regression gate becomes real when live replay lands.

This is also the irony guard: our fixer must not confidently ship a wrong fix —
the same failure class Promptetheus exists to catch.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from promptetheus.server.regression.runner import run_regression

_MODEL = os.environ.get("PROMPTETHEUS_FIX_AGENT_MODEL", "claude-opus-4-8")


@dataclass
class Critique:
    approved: bool
    confidence: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "confidence": self.confidence, "reason": self.reason}


class _CritiqueOut(BaseModel):
    approved: bool = Field(description="True only if the diff actually fixes the root cause.")
    confidence: float = Field(description="0.0-1.0 confidence in the verdict.")
    reason: str = Field(description="One or two sentences justifying the verdict.")


_SYSTEM = (
    "You are a strict reviewer of automated fixes. Given an incident's root cause and a "
    "proposed unified diff, decide whether the diff genuinely addresses the root cause "
    "(not a superficial or unrelated change). Reject vague, empty, or off-target fixes. "
    "Be conservative: when unsure, do not approve."
)


def critique_fix(bundle: dict[str, Any], fix_result: Any) -> Critique:
    """Second Claude pass judging whether the fix addresses the root cause."""

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return Critique(
            approved=True,
            confidence=0.0,
            reason="critique skipped (no ANTHROPIC_API_KEY); gated by regression only",
        )
    try:
        import anthropic
    except Exception:
        return Critique(approved=False, confidence=0.0, reason="critique unavailable (anthropic missing)")

    diff = getattr(fix_result, "diff", None) or ""
    diagnosis = (getattr(fix_result, "metadata", {}) or {}).get("diagnosis", "")
    prompt = "\n".join(
        [
            "## Detected root cause",
            str(bundle.get("root_cause")),
            "",
            "## Fix-agent diagnosis",
            str(diagnosis),
            "",
            "## Proposed diff",
            diff[:8000],
            "",
            "Does this diff actually fix the root cause? Return your verdict.",
        ]
    )
    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=_MODEL,
            max_tokens=2000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=_CritiqueOut,
        )
        out: _CritiqueOut = response.parsed_output
        return Critique(
            approved=bool(out.approved),
            confidence=float(out.confidence),
            reason=str(out.reason),
        )
    except Exception as exc:  # fail closed — never silently approve on error
        return Critique(approved=False, confidence=0.0, reason=f"critique unavailable: {exc}")


def verify(
    store: Any,
    incident: dict[str, Any],
    bundle: dict[str, Any],
    fix_result: Any,
    *,
    pr_url: str | None = None,
) -> dict[str, Any]:
    """Run both gates. `passed` requires critique approval AND a clean regression."""

    critique = critique_fix(bundle, fix_result)
    regression = run_regression(store, incident, pr_url=pr_url)
    regression_passed = int(regression.get("after_fail", 1)) == 0
    passed = critique.approved and regression_passed
    return {
        "passed": passed,
        "critique": critique.as_dict(),
        "regression": regression,
        "regression_passed": regression_passed,
    }


__all__ = ["Critique", "critique_fix", "verify"]
