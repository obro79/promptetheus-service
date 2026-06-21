"""Sentry telemetry sink for eval scores (and a hook for heal-loop spans).

Emits one `gen_ai.evaluate_fix` span per eval case following Sentry's AI agent
monitoring / OpenTelemetry gen_ai conventions, with the fix-quality signals as
span attributes (Sentry attributes only allow primitives). These power the
"healer monitors its own fix quality" scoreboard. Every entry point is wrapped
so a missing `sentry-sdk`, missing DSN, or any SDK error is a silent no-op —
the heal loop must never break because the sink is down.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from promptetheus.server.evals.report import EvalReport

_INITIALIZED = False


def init_sentry() -> bool:
    """Initialize Sentry once from `SENTRY_DSN`. No-op (returns False) when the
    DSN is unset or `sentry-sdk` isn't installed, so the service runs unchanged
    without observability configured. Called from `create_app`."""

    global _INITIALIZED
    if _INITIALIZED:
        return True
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
    except Exception:
        return False
    try:
        sentry_sdk.init(
            dsn=dsn,
            # Capture every heal run for the demo; AI agent (gen_ai) spans need
            # tracing on. anthropic is auto-instrumented when present.
            traces_sample_rate=1.0,
            environment=os.environ.get("PROMPTETHEUS_ENV", "demo"),
            send_default_pii=False,
        )
        _INITIALIZED = True
        return True
    except Exception:
        return False


def _sentry() -> Any | None:
    """Return the sentry_sdk module if installed AND a client is active, else None."""

    try:
        import sentry_sdk
    except Exception:
        return None
    try:
        client = sentry_sdk.get_client()
        if client is None or not client.is_active():
            return None
    except Exception:
        # Older SDKs: fall back to the Hub client check.
        try:
            if sentry_sdk.Hub.current.client is None:
                return None
        except Exception:
            return None
    return sentry_sdk


@contextmanager
def heal_run(incident_id: str, source: str | None = None) -> Iterator[Any]:
    """Open a Sentry transaction for one heal run so the eval spans and the
    auto-instrumented Anthropic `gen_ai` spans attach to a single AI-agent run
    in the dashboard. No-op context when Sentry isn't active."""

    sentry_sdk = _sentry()
    if sentry_sdk is None:
        yield None
        return
    with sentry_sdk.start_transaction(
        op="gen_ai.invoke_agent", name="heal_incident"
    ) as transaction:
        try:
            transaction.set_tag("promptetheus.incident_id", str(incident_id))
            transaction.set_data("gen_ai.operation.name", "invoke_agent")
            transaction.set_data("gen_ai.agent.name", "promptetheus-healer")
            if source:
                transaction.set_data("promptetheus.source", source)
        except Exception:
            pass
        yield transaction


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


__all__ = ["init_sentry", "heal_run", "record_eval"]
