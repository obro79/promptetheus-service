"""Internal row + result shapes shared across the FastAPI server modules.

Storage rows are plain dict objects (they serialize straight to JSON for the
API), while detector/analysis outputs are typed dataclasses because they are the
differentiated core and benefit from a fixed, testable shape. The engine converts
AnalysisResult into the analysis_result storage dict via as_dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Detector + analysis contract (see technical-architecture.md "Detector Semantics")
# ---------------------------------------------------------------------------

DETECTOR_LABELS: tuple[str, ...] = (
    "browser_goal_mismatch",
    "ignored_ui_warning",
    "false_success_claim",
    "forbidden_action",
)

INCIDENT_STATUSES: tuple[str, ...] = (
    "new",
    "triaged",
    "fixing",
    "verified",
    "ignored",
)


@dataclass(frozen=True)
class Detection:
    """One detector verdict over a session's ordered events.

    evidence_refs are event seq numbers so the console can highlight the
    exact steps. critical_step_seq is the lowest seq among the evidence
    whose event *caused* the failure state (per the contract).
    """

    label: str
    confidence: float
    evidence_refs: list[int]
    critical_step_seq: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "critical_step_seq": self.critical_step_seq,
        }


@dataclass
class AnalysisResult:
    """Aggregate analysis for one session: the fired detections + root cause."""

    session_id: str
    detections: list[Detection] = field(default_factory=list)
    critical_step_seq: int | None = None
    confidence: float = 0.0
    root_cause: str | None = None
    fallback: bool = False

    @property
    def labels(self) -> list[str]:
        return [detection.label for detection in self.detections]

    def as_dict(self) -> dict[str, Any]:
        """Render the analysis_result storage/API row.

        The legacy fields trace_id/labels/critical_step_seq/confidence
        are preserved for the locked API contract; detections and root_cause
        carry the richer detector output.
        """

        return {
            "trace_id": self.session_id,
            "session_id": self.session_id,
            "labels": self.labels,
            "critical_step_seq": self.critical_step_seq,
            "confidence": self.confidence,
            "root_cause": self.root_cause,
            "detections": [detection.as_dict() for detection in self.detections],
            "fallback": self.fallback,
        }


# ---------------------------------------------------------------------------
# Fix-agent contract (see "GitHub + Fix-Agent Security Contract")
# ---------------------------------------------------------------------------


@dataclass
class FixAgentResult:
    """Output of FixAgentRunner.run(incident_bundle)."""

    plan: list[str]
    diff: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None
    changed_files: list[str] = field(default_factory=list)
    runner: str = "deterministic"
    confidence: float = 0.0
    evidence_refs: list[int] = field(default_factory=list)
    fallback: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": list(self.plan),
            "diff": self.diff,
            "metadata": dict(self.metadata),
            "summary": self.summary,
            "changed_files": list(self.changed_files),
            "runner": self.runner,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "fallback": self.fallback,
        }


# ---------------------------------------------------------------------------
# Self-healing loop contract (orchestrated remediation)
# ---------------------------------------------------------------------------

#: Terminal states for a heal loop. pr_opened = verified fix awaiting human merge;
#: escalated = attempt budget exhausted without a verified fix.
HEAL_STATUSES: tuple[str, ...] = ("pr_opened", "escalated")


@dataclass
class HealReport:
    """Outcome of the bounded self-healing loop for one incident.

    The loop iterates diagnose -> verify (LLM critique + regression) up to
    max_attempts. On the first verified attempt it opens a PR and STOPS (a human
    merges); if the budget is exhausted it escalates. `trail` carries one entry per
    attempt for the console timeline + audit. `source` threads the agent's origin
    (browserbase / lambda / unknown) through unchanged so the same loop visibly
    heals incidents from any deployment.
    """

    status: str
    incident_id: str
    attempts: int = 0
    source: str = "unknown"
    pr: dict[str, Any] | None = None
    trail: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    workflow_run_id: str | None = None
    orchestrator: str = "inprocess"
    #: When the Redis fix-memory warm-started this heal from a prior verified fix,
    #: the matched neighbour ({from_incident_id, label, score, ...}). None when the
    #: loop started cold (no Redis, or no similar prior fix). Surfacing this is what
    #: makes the data flywheel ("it reused what it learned") visible in the console.
    warm_start: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "incident_id": self.incident_id,
            "attempts": self.attempts,
            "source": self.source,
            "pr": self.pr,
            "trail": list(self.trail),
            "reason": self.reason,
            "workflow_run_id": self.workflow_run_id,
            "orchestrator": self.orchestrator,
            "warm_start": self.warm_start,
        }
