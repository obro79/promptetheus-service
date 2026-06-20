"""Claude-backed fix runner.

Generates a real, verified fix for an incident by prompting Claude
(`claude-opus-4-8`, adaptive thinking) for a structured diagnosis + plan +
new-file unified diff confined to the incident's allowed paths. The diff is
validated with the same path-allowlist machinery the deterministic runner and the
GitHub PR path use, so a Claude-proposed change can never escape the connected
repo's allowed paths.

Hard safety net: any failure — no API key, the `anthropic` package missing, an API
error, a malformed/empty diff, or a path-allowlist violation — falls back to the
DeterministicRunner. The loop therefore never hard-fails on the Claude path.
"""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field

from promptetheus.server.fix_agent.runner import (
    DEFAULT_ALLOWED_PATHS,
    _changed_paths,
    _path_inside,
)
from promptetheus.server.fix_agent.runners.deterministic import DeterministicRunner
from promptetheus.server.models import FixAgentResult

#: Default model + headroom. Adaptive thinking is on; 16000 is the recommended
#: non-streaming max_tokens (stays under the SDK's HTTP-timeout guard).
_MODEL = os.environ.get("PROMPTETHEUS_FIX_AGENT_MODEL", "claude-opus-4-8")
_MAX_TOKENS = 16000
_MAX_EVENTS = 24  # cap events injected into the prompt


class FixProposal(BaseModel):
    """Schema-validated Claude output for a fix."""

    diagnosis: str = Field(description="Root cause of the failure in one or two sentences.")
    plan: list[str] = Field(description="Ordered steps a human reviewer can follow.")
    diff: str = Field(
        description=(
            "A well-formed new-file unified diff (--- /dev/null, +++ b/<path>, @@ hunk) "
            "confined to the allowed paths. Must be parseable and self-contained."
        )
    )


_SYSTEM = (
    "You are Promptetheus's fix agent. You receive a redacted incident bundle for a "
    "failed AI-agent run and produce a concrete code fix as a unified diff. "
    "Constraints you MUST follow: (1) every file you touch MUST live under one of the "
    "allowed paths given in the bundle; (2) emit NEW-FILE diffs only — each file starts "
    "with `--- /dev/null` then `+++ b/<path>` then an `@@ -0,0 +1,N @@` hunk with every "
    "body line prefixed by `+`; (3) the fix must directly address the detected root "
    "cause — add the missing capability/guard that would have prevented the failure. "
    "Keep the diff minimal and self-contained."
)


def _prompt(bundle: dict[str, Any], prior_critique: Any, warm_start: Any) -> str:
    incident = bundle.get("incident") or {}
    allowed = bundle.get("allowed_paths") or list(DEFAULT_ALLOWED_PATHS)
    events = (bundle.get("events") or [])[:_MAX_EVENTS]
    parts = [
        "## Incident",
        f"label: {incident.get('label')}",
        f"severity: {incident.get('severity')}",
        f"confidence: {incident.get('confidence')}",
        f"source: {bundle.get('source')}",
        "",
        "## User goal",
        str(bundle.get("user_goal")),
        "",
        "## Detected root cause",
        str(bundle.get("root_cause")),
        "",
        "## Allowed paths (the diff MUST stay within these)",
        json.dumps(allowed),
        "",
        "## Ordered events around the critical step (redacted)",
        json.dumps(events, default=str)[:8000],
    ]
    if warm_start:
        parts += [
            "",
            "## A verified fix for a similar past incident (adapt, don't copy blindly)",
            json.dumps(warm_start, default=str)[:4000],
        ]
    if prior_critique is not None:
        reason = getattr(prior_critique, "reason", None) or (
            prior_critique.get("reason") if isinstance(prior_critique, dict) else None
        )
        if reason:
            parts += [
                "",
                "## Your previous attempt was REJECTED — fix this and try again",
                str(reason),
            ]
    parts += ["", "Return the diagnosis, plan, and diff."]
    return "\n".join(parts)


class ClaudeRunner:
    """Real Claude fix runner with a deterministic fallback on any failure."""

    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        self.allowed_paths: list[str] = (
            list(allowed_paths) if allowed_paths else list(DEFAULT_ALLOWED_PATHS)
        )

    def run(
        self,
        incident_bundle: dict[str, Any],
        *,
        prior_critique: Any = None,
        warm_start: Any = None,
    ) -> FixAgentResult:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return self._fallback(incident_bundle)
        try:
            import anthropic
        except Exception:
            return self._fallback(incident_bundle)

        try:
            client = anthropic.Anthropic()
            response = client.messages.parse(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": _prompt(incident_bundle, prior_critique, warm_start),
                    }
                ],
                output_format=FixProposal,
            )
            proposal: FixProposal = response.parsed_output
            diff = (proposal.diff or "").strip()
            if not diff:
                return self._fallback(incident_bundle)

            # Security Contract: reject any change outside the runner allow-list.
            changed = _changed_paths(diff)
            if not changed:
                return self._fallback(incident_bundle)
            for path in changed:
                if not _path_inside(path, self.allowed_paths):
                    raise ValueError(
                        "claude fix touches path outside allowed_paths: "
                        f"{path!r} not within {self.allowed_paths!r}"
                    )

            incident = incident_bundle.get("incident") or {}
            return FixAgentResult(
                plan=list(proposal.plan) or ["Apply the generated fix."],
                diff=diff if diff.endswith("\n") else diff + "\n",
                metadata={
                    "fallback": False,
                    "model": _MODEL,
                    "diagnosis": proposal.diagnosis,
                    "allowed_paths": list(self.allowed_paths),
                    "retry": prior_critique is not None,
                    "warm_started": bool(warm_start),
                },
                summary=proposal.diagnosis or "Claude-generated fix.",
                changed_files=changed,
                runner="claude",
                confidence=float(incident.get("confidence") or 0.0),
                evidence_refs=[
                    int(e.get("seq"))
                    for e in incident_bundle.get("events") or []
                    if isinstance(e.get("seq"), int) and not isinstance(e.get("seq"), bool)
                ],
                fallback=False,
            )
        except ValueError:
            # Path-allowlist violation is a hard security stop -> fall back safely.
            return self._fallback(incident_bundle)
        except Exception:
            return self._fallback(incident_bundle)

    def _fallback(self, incident_bundle: dict[str, Any]) -> FixAgentResult:
        return DeterministicRunner(allowed_paths=self.allowed_paths).run(incident_bundle)
