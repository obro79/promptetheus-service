"""Event-driven auto-heal trigger.

When `PROMPTETHEUS_AUTO_HEAL` is enabled, ingesting a failure-signaling event
kicks off the analysis -> incident -> heal pipeline automatically (off the request
path, in a daemon thread) so failures are remediated — e.g. by a Devin session
with advanced similar-fix context when `PROMPTETHEUS_FIX_AGENT_RUNNER=devin` — the
moment they land, without a human clicking "heal" in the console.

Default OFF. Every entry point is wrapped so a trigger failure can never affect
ingestion, and the heavy work always runs in the background.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from promptetheus.server.analysis.engine import analyze_session, assemble_incidents

#: Event types that, on their own or with an error/failed payload, signal a
#: failed run worth auto-healing.
_FAILURE_TYPES: frozenset[str] = frozenset(
    {"error", "tool_result", "goal_check", "session_end"}
)

#: Sessions with an auto-heal run in flight, so concurrent failure events (e.g.
#: SDK retries) don't spawn duplicate runs that open duplicate PRs.
_inflight: set[str] = set()
_inflight_lock = threading.Lock()


def auto_heal_enabled() -> bool:
    raw = os.environ.get("PROMPTETHEUS_AUTO_HEAL", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def is_failure_event(event: dict[str, Any]) -> bool:
    """True when an event signals a failure the heal loop should act on."""

    etype = event.get("type")
    if etype not in _FAILURE_TYPES:
        return False
    payload = event.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    if etype == "error":
        return True
    if etype == "tool_result":
        return bool(payload.get("error")) or payload.get("status") in ("error", "failed")
    if etype == "goal_check":
        return payload.get("passed") is False
    if etype == "session_end":
        status = payload.get("status")
        return bool(payload.get("error")) or (status is not None and status != "completed")
    return False


def maybe_trigger_auto_heal(
    store: Any, session_id: str, accepted_events: list[dict[str, Any]]
) -> bool:
    """Schedule a background auto-heal if enabled and a failure event landed.

    Returns True when a background run was scheduled. Never raises.
    """

    try:
        if not auto_heal_enabled():
            return False
        if not any(is_failure_event(event) for event in accepted_events):
            return False
        with _inflight_lock:
            if session_id in _inflight:
                return False
            _inflight.add(session_id)
        thread = threading.Thread(
            target=_run_and_release,
            args=(store, session_id),
            name=f"auto-heal-{session_id}",
            daemon=True,
        )
        thread.start()
        return True
    except Exception:
        with _inflight_lock:
            _inflight.discard(session_id)
        return False


def _run_and_release(store: Any, session_id: str) -> None:
    """Run the background heal and always clear the in-flight marker."""

    try:
        run_auto_heal(store, session_id)
    finally:
        with _inflight_lock:
            _inflight.discard(session_id)


def run_auto_heal(store: Any, session_id: str) -> dict[str, Any]:
    """Analyze -> assemble incidents -> heal each, synchronously. Never raises.

    Exposed directly (not just via the background thread) so it is unit-testable
    and so an internal job/worker can call it deterministically.
    """

    summary: dict[str, Any] = {"session_id": session_id, "incidents": [], "healed": 0}
    try:
        session = store.get_session(session_id)
        if session is None:
            return summary
        events = store.get_events(session_id)
        result = analyze_session(session, events)
        store.set_analysis(session_id, result.as_dict())
        incidents = assemble_incidents(store, session, result)
        summary["incidents"] = [incident.get("id") for incident in incidents]

        # Imported lazily: the orchestrator pulls in the GitHub PR / runner stack,
        # which we do not want to load on every ingestion import.
        from promptetheus.server.fix_agent.orchestrator import run_loop

        for incident in incidents:
            try:
                report = run_loop(store, incident)
                # Only a PR-opened report is a successful heal; escalated reports
                # exhausted the attempt budget without a verified fix.
                if report.status == "pr_opened":
                    summary["healed"] += 1
                store.add_audit(
                    {
                        "workspace_id": incident.get("workspace_id"),
                        "project_id": incident.get("project_id"),
                        "action": "auto_heal_trigger",
                        "incident_id": incident.get("id"),
                        "session_id": session_id,
                        "actor_kind": "system",
                        "metadata": {
                            "status": report.status,
                            "attempts": report.attempts,
                            "orchestrator": report.orchestrator,
                        },
                    }
                )
            except Exception:
                continue
    except Exception:
        return summary
    return summary


__all__ = [
    "auto_heal_enabled",
    "is_failure_event",
    "maybe_trigger_auto_heal",
    "run_auto_heal",
]
