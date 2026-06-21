"""LLM-as-judge eval suite for the self-healing loop.

This is the *real* regression gate: instead of assuming a fix works (the State-0
deterministic `regression.runner` fallback), it derives an eval case from the
failing trace — the assertion the agent violated, the answer it actually gave,
and the evidence it had — then has a judge model score the agent's *before* and
*after* outputs against that assertion. A fix only passes when the before output
fails the assertion AND the after output passes it (proof the fix flipped the
failure, not a rubber stamp).

Degrades safely: with no `ANTHROPIC_API_KEY`, or when the bundle carries no
failing trace, it falls back to the deterministic before-fail/after-pass record
so the demo still closes — the critique gate in `verifier` remains the
fail-closed safety net.
"""

from __future__ import annotations

from promptetheus.server.evals.dataset import EvalCase, derive_cases
from promptetheus.server.evals.report import EvalCaseResult, EvalReport
from promptetheus.server.evals.runner import run_eval_suite

__all__ = [
    "EvalCase",
    "EvalCaseResult",
    "EvalReport",
    "derive_cases",
    "run_eval_suite",
]
