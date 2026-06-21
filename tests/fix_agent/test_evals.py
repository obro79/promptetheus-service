"""Locks for the LLM-as-judge eval suite (the real regression gate).

The load-bearing invariant for the demo money-shot: on a real judged run the
agent's BEFORE output fails the violated assertion and the AFTER output passes
it, so `EvalReport.passed` is True only because the fix flipped the failure.
Also covers: non-blocking when there's no failing trace, deterministic fallback
when no judge is configured, and blocking when the fix did not actually work.
"""

from __future__ import annotations

import json
from typing import Any

from promptetheus.server.evals import derive_cases, run_eval_suite
from promptetheus.server.evals.judge import _EvalOut


def _bundle_with_failure() -> dict[str, Any]:
    """A redacted-bundle shape carrying the insurance contradiction trace."""

    return {
        "incident": {"id": "incident_1", "label": "goal_mismatch"},
        "user_goal": "Tell the patient whether Lisinopril is covered",
        "events": [
            {
                "type": "user_message",
                "payload": {"content": "Is my Lisinopril covered?"},
                "seq": 1,
            },
            {
                "type": "retrieval",
                "payload": {
                    "query": "Lisinopril coverage",
                    "documents": [
                        {"drug": "Lisinopril", "covered": True, "tier": 1, "copay_usd": 10}
                    ],
                },
                "seq": 2,
            },
            {
                "type": "agent_message",
                "payload": {"content": "Unfortunately Lisinopril isn't covered."},
                "seq": 3,
            },
            {
                "type": "goal_check",
                "payload": {
                    "passed": False,
                    "mismatches": [
                        "Retrieved that Lisinopril is covered ($10 copay) but told the "
                        "user it is NOT covered"
                    ],
                },
                "seq": 4,
            },
        ],
    }


class _Resp:
    def __init__(self, parsed: _EvalOut) -> None:
        self.parsed_output = parsed


def _install_judge(monkeypatch, verdict_for) -> None:
    """Patch anthropic so parse() returns a verdict chosen from the prompt text.

    `verdict_for(prompt_text) -> bool` decides `satisfies`, letting a test make
    the before output fail and the after output pass off the same fake.
    """

    import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")

    class _Messages:
        def parse(self, **kwargs: Any) -> _Resp:
            text = json.dumps(kwargs.get("messages"))
            satisfies = verdict_for(text)
            return _Resp(_EvalOut(satisfies=satisfies, confidence=0.9, reason="t"))

    class _Client:
        def __init__(self, *a: Any, **k: Any) -> None:
            self.messages = _Messages()

    monkeypatch.setattr(anthropic, "Anthropic", _Client)


# --- case derivation -------------------------------------------------------


def test_derive_case_from_failing_trace() -> None:
    cases = derive_cases(_bundle_with_failure())
    assert len(cases) == 1
    case = cases[0]
    assert "isn't covered" in case.before_output
    assert "Lisinopril" in case.assertion
    assert "covered" in case.context


def test_no_cases_without_failing_trace() -> None:
    assert derive_cases({"events": []}) == []
    assert derive_cases({}) == []


# --- the money-shot lock ---------------------------------------------------


def test_before_fails_after_passes(monkeypatch) -> None:
    failing_answer = "Unfortunately Lisinopril isn't covered."
    # Judge says: the before answer (the contradiction) does NOT satisfy; any
    # other candidate (the evidence-grounded fix) DOES.
    _install_judge(monkeypatch, lambda text: failing_answer not in text)

    report = run_eval_suite(_bundle_with_failure())

    assert report.meaningful is True
    assert report.fallback is False
    assert report.before_fail == 1
    assert report.after_fail == 0
    assert report.passed is True


def test_blocks_when_fix_does_not_work(monkeypatch) -> None:
    # Judge rejects everything -> the after output still fails -> gate blocks.
    _install_judge(monkeypatch, lambda text: False)

    report = run_eval_suite(_bundle_with_failure())

    assert report.after_fail == 1
    assert report.passed is False


# --- safe degradation ------------------------------------------------------


def test_deterministic_fallback_without_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    report = run_eval_suite(_bundle_with_failure())

    assert report.fallback is True
    assert report.before_fail == 1
    assert report.after_fail == 0
    assert report.passed is True


def test_non_blocking_when_no_trace() -> None:
    report = run_eval_suite({"events": []})

    assert report.meaningful is False
    assert report.passed is True
