"""Fix-agent runner registry (State-0: deterministic only)."""

from __future__ import annotations

import os
from typing import Any, Protocol

from promptetheus.server.models import FixAgentResult


class IncidentRunner(Protocol):
    def run(self, incident_bundle: dict[str, Any]) -> FixAgentResult: ...


def fix_agent_fallback_forced() -> bool:
    raw = os.environ.get("PROMPTETHEUS_FIX_AGENT_FALLBACK", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_runner(
    name: str | None = None, *, allowed_paths: list[str] | None = None
) -> IncidentRunner:
    runner_name = (
        name
        or os.environ.get("PROMPTETHEUS_FIX_AGENT_RUNNER", "deterministic")
    ).strip().lower()
    if runner_name == "codex":
        from .codex import CodexRunner

        return CodexRunner(allowed_paths=allowed_paths)
    if runner_name == "claude":
        from .claude import ClaudeRunner

        return ClaudeRunner(allowed_paths=allowed_paths)
    from .deterministic import DeterministicRunner

    return DeterministicRunner(allowed_paths=allowed_paths)


def resolve_fix_agent_runner(*, allowed_paths: list[str] | None = None) -> IncidentRunner:
    return get_runner(allowed_paths=allowed_paths)


__all__ = [
    "IncidentRunner",
    "fix_agent_fallback_forced",
    "get_runner",
    "resolve_fix_agent_runner",
]
