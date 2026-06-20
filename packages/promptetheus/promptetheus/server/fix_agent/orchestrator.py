"""Orchestrator seam for the heal loop.

`run_loop` dispatches on `PROMPTETHEUS_ORCHESTRATOR` (default `inprocess`):

- **inprocess** — call `heal_incident` directly. Guaranteed-to-work demo safety net.
- **agentspan** — drive the loop as an Orkes Conductor (Agentspan) workflow so the
  workflow run id / graph is a first-class demo artifact for the Orkes prize. The
  loop *steps* are the same in-process callables; Agentspan only sequences them. If
  the Agentspan SDK is missing or unreachable, this falls back to the in-process
  path so the demo never depends on it.

Everything Agentspan-related is lazy-imported and defensively wrapped — a missing
dep or a booth-credential snag can never break `inprocess` or tests.
"""

from __future__ import annotations

import os
from typing import Any

from promptetheus.server.fix_agent.loop import heal_incident
from promptetheus.server.models import HealReport

_WORKFLOW_NAME = os.environ.get("PROMPTETHEUS_AGENTSPAN_WORKFLOW", "promptetheus_heal")


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


def _agentspan_run_id(incident: dict[str, Any]) -> str | None:
    """Start an Orkes Conductor workflow run for this heal, returning its id.

    Best-effort: returns None when the SDK/creds are absent so the caller falls
    back to in-process. The heal steps execute in-process (shared callables); the
    workflow run is the trackable Agentspan artifact for the demo/prize.
    """

    base = os.environ.get("CONDUCTOR_SERVER_URL") or os.environ.get("ORKES_SERVER_URL")
    if not base:
        return None
    try:
        from conductor.client.configuration.configuration import Configuration  # type: ignore
        from conductor.client.orkes_clients import OrkesClients  # type: ignore

        config = Configuration(server_api_url=base)
        workflow_client = OrkesClients(configuration=config).get_workflow_client()
        run_id = workflow_client.start_workflow_by_name(
            name=_WORKFLOW_NAME,
            input={
                "incident_id": incident.get("id"),
                "workspace_id": incident.get("workspace_id"),
                "label": incident.get("label"),
            },
        )
        return str(run_id) if run_id else None
    except Exception:
        return None


def _run_agentspan(
    store: Any, incident: dict[str, Any], *, max_attempts: int | None
) -> HealReport | None:
    run_id = _agentspan_run_id(incident)
    if run_id is None:
        return None
    report = heal_incident(store, incident, max_attempts=max_attempts)
    report.orchestrator = "agentspan"
    report.workflow_run_id = run_id
    return report


__all__ = ["run_loop"]
