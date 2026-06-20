"""Deterministic fallback fix runner (State-0 default)."""

from __future__ import annotations

import os
from typing import Any

from promptetheus.server.fix_agent.runner import FixAgentRunner, _changed_paths
from promptetheus.server.models import FixAgentResult


def _fix_agent_fallback_forced() -> bool:
    raw = os.environ.get("PROMPTETHEUS_FIX_AGENT_FALLBACK", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


class DeterministicRunner:
    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        self._inner = FixAgentRunner(allowed_paths=allowed_paths)

    def run(self, incident_bundle: dict[str, Any]) -> FixAgentResult:
        result = self._inner.run(incident_bundle)
        diff = result.diff or ""
        changed = _changed_paths(diff)
        evidence: list[int] = []
        for event in incident_bundle.get("events") or []:
            seq = event.get("seq")
            if isinstance(seq, int) and not isinstance(seq, bool):
                evidence.append(seq)
        fallback = bool(result.metadata.get("fallback", True)) or _fix_agent_fallback_forced()
        summary = (
            "Deterministic fallback fix: add a post-action goal verification guard."
            if fallback
            else "Deterministic fix plan generated from incident evidence."
        )
        return FixAgentResult(
            plan=result.plan,
            diff=result.diff,
            metadata={**result.metadata, "fallback": fallback},
            summary=summary,
            changed_files=changed,
            runner="deterministic",
            confidence=float(incident_bundle.get("incident", {}).get("confidence") or 0.0),
            evidence_refs=sorted(set(evidence)),
            fallback=fallback,
        )
