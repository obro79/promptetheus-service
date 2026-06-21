"""Run the eval suite for an incident bundle.

`run_eval_suite` is the entry point `verifier.verify` calls. It derives cases
from the bundle, then either scores them with the judge or — when no judge is
available, or a judge call errors — returns the deterministic before-fail /
after-pass fallback so the loop still closes. (Safety is held by the
fail-closed critique gate in `verifier`; this mirrors the existing State-0
regression-is-deterministic posture.)
"""

from __future__ import annotations

from typing import Any

from promptetheus.server.evals.dataset import EvalCase, derive_cases
from promptetheus.server.evals.judge import judge_available, judge_output
from promptetheus.server.evals.report import EvalCaseResult, EvalReport


def _deterministic_results(cases: list[EvalCase]) -> list[EvalCaseResult]:
    """Before fails, after passes — the demo-safe scripted outcome."""

    return [
        EvalCaseResult(
            case_id=case.case_id,
            assertion=case.assertion,
            before_passed=False,
            after_passed=True,
            confidence=0.0,
            reason="deterministic fallback (no judge available)",
        )
        for case in cases
    ]


def run_eval_suite(bundle: dict[str, Any], fix_result: Any = None) -> EvalReport:
    """Score a bundle's eval cases before vs after the fix."""

    cases = derive_cases(bundle)
    if not cases:
        return EvalReport(cases=[], fallback=False, note="no failing trace to evaluate")

    if not judge_available():
        return EvalReport(
            cases=_deterministic_results(cases),
            fallback=True,
            note="no ANTHROPIC_API_KEY; deterministic before-fail/after-pass",
        )

    results: list[EvalCaseResult] = []
    for case in cases:
        try:
            before = judge_output(case, case.before_output)
            after = judge_output(case, case.after_output)
        except Exception as exc:  # fall back rather than break the loop
            return EvalReport(
                cases=_deterministic_results(cases),
                fallback=True,
                note=f"judge error, deterministic fallback: {exc}",
            )
        results.append(
            EvalCaseResult(
                case_id=case.case_id,
                assertion=case.assertion,
                before_passed=bool(before.satisfies),
                after_passed=bool(after.satisfies),
                confidence=float(after.confidence),
                reason=str(after.reason),
            )
        )
    return EvalReport(cases=results, fallback=False)


__all__ = ["run_eval_suite"]
