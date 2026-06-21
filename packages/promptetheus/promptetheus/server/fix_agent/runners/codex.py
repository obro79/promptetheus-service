"""Codex fix runner (deferred to P17)."""

from __future__ import annotations

from typing import Any

from promptetheus.server.models import FixAgentResult


class CodexRunner:
    """Real Codex integration lands in P16.3 / P17."""

    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        self.allowed_paths = allowed_paths

    def run(self, incident_bundle: dict[str, Any], **_: Any) -> FixAgentResult:
        raise NotImplementedError(
            "Codex fix-agent runner is not wired in State-0; set "
            "PROMPTETHEUS_FIX_AGENT_RUNNER=deterministic"
        )
