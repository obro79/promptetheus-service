"""The bounded self-healing loop.

Drives diagnose -> verify (LLM critique + regression) up to `max_attempts`. On the
first verified attempt it opens a PR and STOPS — a human merges (no auto-merge). If
the attempt budget is exhausted, it escalates. Every attempt is audited and
published to the Redis heal timeline.

Step functions (`diagnose_step`, `verify_step`, `pr_step`) are plain callables so an
Agentspan/Conductor workflow can drive the same code the in-process orchestrator
uses — Agentspan sequences these, it does not reimplement them.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from promptetheus.server.fix_agent import memory
from promptetheus.server.fix_agent.runner import build_incident_bundle
from promptetheus.server.fix_agent.runners.claude import ClaudeRunner
from promptetheus.server.fix_agent.verifier import verify
from promptetheus.server.github import (
    GitHubConfig,
    create_pull_request,
    github_fallback_forced,
    github_pr_enabled,
)
from promptetheus.server.models import HealReport


def _max_attempts(explicit: int | None) -> int:
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    raw = os.environ.get("PROMPTETHEUS_HEAL_MAX_ATTEMPTS", "3")
    try:
        value = int(raw)
        return value if value > 0 else 3
    except ValueError:
        return 3


def diagnose_step(
    bundle: dict[str, Any],
    runner: ClaudeRunner,
    *,
    prior_critique: Any = None,
    warm_start: Any = None,
) -> Any:
    """Generate a candidate fix (Claude, with deterministic fallback)."""

    return runner.run(bundle, prior_critique=prior_critique, warm_start=warm_start)


def verify_step(
    store: Any, incident: dict[str, Any], bundle: dict[str, Any], fix: Any
) -> dict[str, Any]:
    """Run both gates (LLM critique + regression)."""

    return verify(store, incident, bundle, fix)


def pr_step(
    incident: dict[str, Any], bundle: dict[str, Any], fix: Any
) -> dict[str, Any] | None:
    """Open a real PR, or a labeled fallback preview when GitHub is disabled."""

    config = GitHubConfig.from_env()
    try:
        result = create_pull_request(
            fix_result=fix, incident=incident, bundle=bundle, config=config
        )
    except Exception:
        result = None
    if result is None:
        # GitHub disabled -> still surface a fallback-preview PR for the report.
        try:
            result = create_pull_request(
                fix_result=fix,
                incident=incident,
                bundle=bundle,
                config=replace(config, fallback=True, enabled=True),
            )
        except Exception:
            return None
    return result.as_dict() if result is not None else None


def _audit_attempt(
    store: Any, incident: dict[str, Any], attempt: int, fix: Any, record: dict[str, Any]
) -> None:
    try:
        store.add_audit(
            {
                "workspace_id": incident.get("workspace_id"),
                "project_id": incident.get("project_id"),
                "action": "heal_attempt",
                "incident_id": incident.get("id"),
                "actor_kind": "system",
                "metadata": {
                    "attempt": attempt,
                    "runner": getattr(fix, "runner", None),
                    "passed": record.get("passed"),
                    "critique": record.get("critique"),
                    "regression": {
                        "after_pass": record.get("regression", {}).get("after_pass"),
                        "after_fail": record.get("regression", {}).get("after_fail"),
                        "before_fail": record.get("regression", {}).get("before_fail"),
                    },
                },
            }
        )
    except Exception:
        pass


def _attempt_event(attempt: int, fix: Any, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "attempt",
        "attempt": attempt,
        "runner": getattr(fix, "runner", None),
        "diagnosis": (getattr(fix, "metadata", {}) or {}).get("diagnosis")
        or getattr(fix, "summary", None),
        "critique": record.get("critique"),
        "regression": record.get("regression"),
        "passed": record.get("passed"),
    }


def run_attempts(
    store: Any, incident: dict[str, Any], *, max_attempts: int | None = None
) -> dict[str, Any]:
    """Run diagnose -> verify up to the attempt cap WITHOUT opening a PR.

    This is the shared core of both the in-process loop (`heal_incident`, which
    opens the PR itself) and the Agentspan approval flow (which opens the PR only
    after a human approves the gated tool). Returns a result dict carrying the
    verified fix (or None), the bundle, the trail, the source, and the attempt
    count — everything `open_verified_fix` needs to finish the job.
    """

    cap = _max_attempts(max_attempts)
    incident_id = str(incident.get("id") or "incident")
    bundle = build_incident_bundle(store, incident)
    source = bundle.get("source") or "unknown"
    runner = ClaudeRunner(allowed_paths=bundle.get("allowed_paths"))

    warm = memory.find_similar_fix(bundle)
    if warm:
        memory.timeline_publish(
            incident_id,
            {"kind": "warm_start", "from": warm.get("from_incident_id"), "score": warm.get("score")},
        )

    trail: list[dict[str, Any]] = []
    critique: Any = None

    for attempt in range(1, cap + 1):
        fix = diagnose_step(bundle, runner, prior_critique=critique, warm_start=warm)
        record = verify_step(store, incident, bundle, fix)
        critique = record.get("critique")
        _audit_attempt(store, incident, attempt, fix, record)
        event = _attempt_event(attempt, fix, record)
        trail.append(event)
        memory.timeline_publish(incident_id, event)
        warm = None  # only warm-start the first attempt

        if record.get("passed"):
            return {
                "verified": True,
                "fix": fix,
                "bundle": bundle,
                "trail": trail,
                "source": source,
                "attempts": attempt,
                "incident_id": incident_id,
            }

    return {
        "verified": False,
        "fix": None,
        "bundle": bundle,
        "trail": trail,
        "source": source,
        "attempts": cap,
        "incident_id": incident_id,
    }


def open_verified_fix(
    store: Any, incident: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any] | None:
    """Open the PR for a verified `run_attempts` result, remember it, finalize.

    Used both by `heal_incident` (immediately) and by the Agentspan approval-gated
    tool (only after a human approves). Returns the PR dict (or None).
    """

    bundle = result["bundle"]
    fix = result["fix"]
    pr = pr_step(incident, bundle, fix)
    memory.remember_fix(incident, bundle, fix)
    _finalize_incident(store, incident, fix, pr)
    memory.timeline_publish(
        result["incident_id"], {"kind": "pr_opened", "attempts": result["attempts"], "pr": pr}
    )
    return pr


def heal_incident(
    store: Any, incident: dict[str, Any], *, max_attempts: int | None = None
) -> HealReport:
    """Run the bounded heal loop for one incident. Stops at the PR; human merges."""

    result = run_attempts(store, incident, max_attempts=max_attempts)
    incident_id = result["incident_id"]

    if result["verified"]:
        pr = open_verified_fix(store, incident, result)
        return HealReport(
            status="pr_opened",
            incident_id=incident_id,
            attempts=result["attempts"],
            source=result["source"],
            pr=pr,
            trail=result["trail"],
        )

    memory.timeline_publish(
        incident_id, {"kind": "escalated", "attempts": result["attempts"], "reason": "max_attempts"}
    )
    return HealReport(
        status="escalated",
        incident_id=incident_id,
        attempts=result["attempts"],
        source=result["source"],
        trail=result["trail"],
        reason="max_attempts",
    )


def _finalize_incident(
    store: Any, incident: dict[str, Any], fix: Any, pr: dict[str, Any] | None
) -> None:
    """Mirror dispatch_fix_agent: attach result + pr_url, audit. Never raises."""

    incident_id = incident.get("id")
    patch: dict[str, Any] = {"fix_agent_result": fix.as_dict(), "status": "fixing"}
    if pr and pr.get("pr_url"):
        patch["pr_url"] = pr["pr_url"]
    try:
        store.update_incident(incident_id, patch)
    except Exception:
        pass
    try:
        store.add_audit(
            {
                "workspace_id": incident.get("workspace_id"),
                "project_id": incident.get("project_id"),
                "action": "github_pr_create",
                "incident_id": incident_id,
                "actor_kind": "system",
                "metadata": pr or {},
            }
        )
    except Exception:
        pass


# Optional re-export so an orchestrator can check whether real GitHub is on.
def github_active() -> bool:
    return github_pr_enabled() or github_fallback_forced()


__all__ = [
    "heal_incident",
    "run_attempts",
    "open_verified_fix",
    "diagnose_step",
    "verify_step",
    "pr_step",
    "github_active",
]
