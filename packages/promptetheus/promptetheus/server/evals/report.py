"""Eval result value objects.

Kept in their own module so both the dataset/runner and the observability sink
import them without pulling in the judge (and its lazy `anthropic`) dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalCaseResult:
    """One case scored before and after the fix."""

    case_id: str
    assertion: str
    before_passed: bool
    after_passed: bool
    confidence: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "assertion": self.assertion,
            "before_passed": self.before_passed,
            "after_passed": self.after_passed,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class EvalReport:
    """Aggregate verdict over every eval case for an incident."""

    cases: list[EvalCaseResult] = field(default_factory=list)
    fallback: bool = False
    note: str | None = None

    @property
    def meaningful(self) -> bool:
        """True when there was an actual failing trace to evaluate."""

        return bool(self.cases)

    @property
    def before_fail(self) -> int:
        return sum(1 for case in self.cases if not case.before_passed)

    @property
    def after_fail(self) -> int:
        return sum(1 for case in self.cases if not case.after_passed)

    @property
    def passed(self) -> bool:
        """Gate verdict.

        No cases -> nothing to evaluate, non-blocking pass. Deterministic
        fallback -> pass (the critique gate stays the fail-closed net). A real
        run only passes when every after output is clean AND the before output
        actually failed (so we know the fix did the flipping).
        """

        if not self.cases:
            return True
        if self.fallback:
            return True
        return self.after_fail == 0 and self.before_fail > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "meaningful": self.meaningful,
            "fallback": self.fallback,
            "before_fail": self.before_fail,
            "after_fail": self.after_fail,
            "note": self.note,
            "cases": [case.as_dict() for case in self.cases],
        }


__all__ = ["EvalCaseResult", "EvalReport"]
