"""Sentry telemetry sink for eval scores (and a hook for heal-loop spans).

Emits one `gen_ai.evaluate_fix` span per eval case following Sentry's AI agent
monitoring / OpenTelemetry gen_ai conventions, with the fix-quality signals as
span attributes (Sentry attributes only allow primitives). These power the
"healer monitors its own fix quality" scoreboard. Every entry point is wrapped
so a missing `sentry-sdk`, missing DSN, or any SDK error is a silent no-op —
the heal loop must never break because the sink is down.
"""

from __future__ import annotations

from typing import Any

from promptetheus.server.evals.report import EvalReport


def _sentry() -> Any | None:
    """Return the sentry_sdk module if installed AND a client is active, else None."""

    try:
        import sentry_sdk
    except Exception:
        return None
    try:
        # Hub.client is None until sentry_sdk.init() ran with a DSN.
        if sentry_sdk.Hub.current.client is None:
            return None
    except Exception:
        return None
    return sentry_sdk


def record_eval(incident: dict[str, Any], report: EvalReport) -> None:
    """Push each eval case to Sentry as a gen_ai span. Never raises."""

    sentry_sdk = _sentry()
    if sentry_sdk is None or not report.meaningful:
        return

    incident_id = str(incident.get("id") or "incident")
    try:
        sentry_sdk.set_tag("promptetheus.incident_id", incident_id)
        for case in report.cases:
            with sentry_sdk.start_span(
                op="gen_ai.evaluate_fix", name="evaluate_fix fix-quality"
            ) as span:
                span.set_data("gen_ai.operation.name", "evaluate_fix")
                span.set_data("promptetheus.incident_id", incident_id)
                span.set_data("eval.case_id", case.case_id)
                span.set_data("eval.before_passed", case.before_passed)
                span.set_data("eval.after_passed", case.after_passed)
                span.set_data("eval.confidence", float(case.confidence))
                span.set_data("eval.fallback", report.fallback)
        # Summary signals for dashboards/alerts on the enclosing transaction.
        scope_span = sentry_sdk.get_current_span()
        if scope_span is not None:
            scope_span.set_data("eval.before_fail", report.before_fail)
            scope_span.set_data("eval.after_fail", report.after_fail)
            scope_span.set_data("eval.passed", report.passed)
    except Exception:
        return


__all__ = ["record_eval"]
