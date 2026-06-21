"""Orchestrator seam for the heal loop.

`run_loop` dispatches on `PROMPTETHEUS_ORCHESTRATOR` (default `inprocess`):

- **inprocess** — call `heal_incident` directly. Guaranteed-to-work demo safety net.
- **agentspan** — run the heal as a real Agentspan execution (the durable agent
  runtime at https://agentspan.ai) so the execution id / live graph in the
  Agentspan UI (http://localhost:6767) is a first-class demo artifact for the
  prize. The bounded loop itself is exposed to the runtime as a single `@tool`,
  so the proven deterministic loop still does the healing — Agentspan provides
  the durable, trackable execution wrapper. If the Agentspan SDK is missing or
  the server is unreachable, this falls back to the in-process path so the demo
  never depends on it.

Everything Agentspan-related is lazy-imported and defensively wrapped — a missing
dep or a booth-credential snag can never break `inprocess` or tests.
"""

from __future__ import annotations

import os
from typing import Any

from promptetheus.server.fix_agent.loop import heal_incident
from promptetheus.server.models import HealReport

#: The Agentspan agent's model, in Agentspan's "provider/model" form. Defaults to
#: the project's house model; override if the Agentspan gateway routes a different
#: id (their docs example uses "anthropic/claude-sonnet-4-6").
_AGENTSPAN_MODEL = os.environ.get(
    "PROMPTETHEUS_AGENTSPAN_MODEL", "anthropic/claude-opus-4-8"
)


def _mode(explicit: str | None) -> str:
    raw = (explicit or os.environ.get("PROMPTETHEUS_ORCHESTRATOR", "inprocess")).strip().lower()
    return raw if raw in {"inprocess", "agentspan"} else "inprocess"


def run_loop(
    store: Any,
    incident: dict[str, Any],
    *,
    mode: str | None = None,
    max_attempts: int | None = None,
) -> HealReport:
    selected = _mode(mode)
    if selected == "agentspan":
        report = _run_agentspan(store, incident, max_attempts=max_attempts)
        if report is not None:
            return report
        # fall through to in-process on any Agentspan failure
    report = heal_incident(store, incident, max_attempts=max_attempts)
    report.orchestrator = "inprocess"
    return report


def _run_agentspan(
    store: Any, incident: dict[str, Any], *, max_attempts: int | None
) -> HealReport | None:
    """Run the heal as a durable Agentspan execution; return its HealReport.

    The bounded loop is exposed to the Agentspan runtime as a single `@tool`, so
    the LLM agent invokes it and Agentspan records a durable, trackable execution
    (visible in the UI at http://localhost:6767). `AgentResult.workflow_id` — the
    execution id — is stamped onto the report as the demo artifact.

    Best-effort: returns None on any failure (SDK absent, server unreachable, the
    agent never calling the tool) so the caller falls back to in-process. The heal
    itself still runs deterministically inside the tool regardless of the LLM.
    """

    # The tool captures the authoritative HealReport so we never depend on the
    # LLM's narration of the result — the deterministic loop is the source of truth.
    holder: dict[str, HealReport] = {}

    # The whole construction (import, @tool decoration, Agent build, run) is guarded
    # so any Agentspan failure — missing dep, bad model route, server unreachable —
    # degrades to the in-process loop instead of breaking the heal.
    try:
        from agentspan.agents import Agent, AgentRuntime, tool  # type: ignore

        @tool
        def heal_incident_tool(incident_id: str) -> dict[str, Any]:
            """Run the bounded self-healing loop for the incident and return its report.

            Args:
                incident_id: The id of the incident to heal.
            """

            report = heal_incident(store, incident, max_attempts=max_attempts)
            holder["report"] = report
            return report.as_dict()

        agent = Agent(
            name="promptetheus-healer",
            model=_AGENTSPAN_MODEL,
            tools=[heal_incident_tool],
            instructions=(
                "You remediate a failed AI-agent incident. Call heal_incident_tool "
                "exactly once with the given incident id, then stop and report whether "
                "a pull request was opened. Do not call any other tool."
            ),
            max_turns=4,
        )

        with AgentRuntime() as runtime:
            result = runtime.run(agent, f"Heal incident {incident.get('id')}.")
    except Exception:
        return None

    # If the agent declined to call the tool, still heal deterministically so the
    # agentspan path is never weaker than in-process.
    report = holder.get("report") or heal_incident(
        store, incident, max_attempts=max_attempts
    )
    report.orchestrator = "agentspan"
    # The docs call this `workflow_id`; the runtime logs it as `execution_id`.
    # Read both so the trackable id (the demo artifact) is always captured.
    report.workflow_run_id = (
        getattr(result, "workflow_id", None) or getattr(result, "execution_id", None)
    )
    return report


__all__ = ["run_loop"]
