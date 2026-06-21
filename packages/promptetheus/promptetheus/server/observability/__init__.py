"""Observability sinks for the self-healing loop.

Thin, lazy-imported wrappers that push heal-loop telemetry to Sentry's AI agent
monitoring (gen_ai spans) and eval scores. Everything degrades to a no-op when
`sentry-sdk` isn't installed or no DSN is configured, so the loop never depends
on the sink being present.
"""

from __future__ import annotations

from promptetheus.server.observability import telemetry

__all__ = ["telemetry"]
