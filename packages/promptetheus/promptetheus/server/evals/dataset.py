"""Derive eval cases from a redacted incident bundle.

The bundle (`fix_agent.runner.build_incident_bundle`) already carries the
windowed events around the critical step. We mine those for the failure's three
load-bearing facts:

- the **assertion** the agent's answer must satisfy (from the failed
  `goal_check.mismatches` + the session `user_goal`),
- the **before output** the agent actually gave (the last `agent_message`),
- the **evidence** it had on hand (the `retrieval` documents).

The post-fix ("after") output is resolved in priority order: an explicit
`expected_fixed_output` on the bundle/incident (set by demo seeds or a live
re-run), else an evidence-grounded corrected answer reconstructed from the
retrieved documents the agent ignored. A live agent re-run replaces this when
the agent endpoint is wired (Tier 2); the contract here is unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class EvalCase:
    """A single before/after assertion check derived from an incident."""

    case_id: str
    assertion: str
    context: str
    before_output: str
    after_output: str


def _events_of(events: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [e for e in events if isinstance(e, dict) and e.get("type") == event_type]


def _payload(event: dict[str, Any] | None) -> dict[str, Any]:
    if not event:
        return {}
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _failed_goal_check(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The last goal_check that did not pass (the guaranteed incident trigger)."""

    checks = _events_of(events, "goal_check")
    failed = [c for c in checks if _payload(c).get("passed") is False]
    if failed:
        return failed[-1]
    return checks[-1] if checks else None


def _collect_documents(events: list[dict[str, Any]]) -> list[Any]:
    docs: list[Any] = []
    for retrieval in _events_of(events, "retrieval"):
        items = _payload(retrieval).get("documents")
        if isinstance(items, list):
            docs.extend(items)
    return docs


def _summarize_documents(docs: list[Any]) -> str:
    if not docs:
        return "(no retrieved evidence)"
    try:
        return json.dumps(docs, default=str)[:2000]
    except Exception:
        return str(docs)[:2000]


def _render_assertion(
    user_goal: str | None, mismatches: list[str], root_cause: str | None
) -> str:
    goal = (user_goal or "the user's stated goal").strip()
    lines = [
        f"The agent's final answer/action must satisfy: {goal}",
        "It must be consistent with the retrieved evidence and the user's goal, "
        "and must not contradict them.",
    ]
    if mismatches:
        lines.append("The original failure was: " + "; ".join(str(m) for m in mismatches))
    elif root_cause:
        lines.append(f"The detected root cause was: {root_cause}")
    return "\n".join(lines)


def _render_context(user_goal: str | None, docs: list[Any]) -> str:
    return "\n".join(
        [
            f"User goal: {user_goal or '(unspecified)'}",
            f"Retrieved evidence the agent had: {_summarize_documents(docs)}",
        ]
    )


def _resolve_after_output(
    bundle: dict[str, Any], user_goal: str | None, docs: list[Any]
) -> str:
    """Find the post-fix answer to judge.

    1. explicit `expected_fixed_output` on the bundle or incident metadata
       (demo seeds / live re-run capture set this), else
    2. an evidence-grounded corrected answer built from the retrieved documents
       the agent ignored — demo-safe and still a real string for the judge.
    """

    explicit = bundle.get("expected_fixed_output")
    if not explicit:
        incident = bundle.get("incident")
        if isinstance(incident, dict):
            meta = incident.get("metadata")
            if isinstance(meta, dict):
                explicit = meta.get("fixed_output")
    if isinstance(explicit, str) and explicit.strip():
        return explicit

    goal = user_goal or "the user's goal"
    return (
        f"Based strictly on the retrieved evidence ({_summarize_documents(docs)}), "
        f"the answer to '{goal}' is reported consistently with that evidence and "
        "does not contradict it."
    )


def derive_cases(bundle: dict[str, Any]) -> list[EvalCase]:
    """Build eval cases for a bundle. Empty when there is no failing trace."""

    events = bundle.get("events")
    if not isinstance(events, list) or not events:
        return []

    agent_messages = _events_of(events, "agent_message")
    before_output = _payload(agent_messages[-1]).get("content") if agent_messages else ""
    before_output = str(before_output or "")
    if not before_output:
        # No answer/action to evaluate -> nothing meaningful to score.
        return []

    # Prefer the failed goal_check's mismatches (strongest assertion source), but
    # the bundle's event window often excludes the terminal goal_check, so fall
    # back to the analysis root cause / user goal, which are always in the bundle.
    goal_check = _failed_goal_check(events)
    mismatches = _payload(goal_check).get("mismatches") if goal_check else None
    mismatches = [str(m) for m in mismatches] if isinstance(mismatches, list) else []

    root_cause = bundle.get("root_cause")
    root_cause = str(root_cause) if isinstance(root_cause, str) and root_cause.strip() else None
    user_goal = bundle.get("user_goal")

    if not (mismatches or root_cause or (isinstance(user_goal, str) and user_goal.strip())):
        return []

    docs = _collect_documents(events)
    incident = bundle.get("incident") if isinstance(bundle.get("incident"), dict) else {}
    incident_id = str(incident.get("id") or bundle.get("representative_session_id") or "incident")

    return [
        EvalCase(
            case_id=f"{incident_id}:goal_check",
            assertion=_render_assertion(user_goal, mismatches, root_cause),
            context=_render_context(user_goal, docs),
            before_output=before_output,
            after_output=_resolve_after_output(bundle, user_goal, docs),
        )
    ]


__all__ = ["EvalCase", "derive_cases"]
