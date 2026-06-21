"""Devin-backed fix runner.

Dispatches a real fix to the Devin API: it creates a session
(`POST /v1/sessions`) seeded with the redacted incident bundle and — crucially —
the **advanced context** of the top similar past fixes retrieved from Redis
vector memory, then polls the session (`GET /v1/sessions/{id}`) for a validated
structured output of `{diagnosis, plan, diff}`. The diff is checked against the
same path-allowlist machinery the deterministic / Claude runners and the GitHub
PR path use, so a Devin-proposed change can never escape the connected repo's
allowed paths.

Hard safety net: any failure — no `DEVIN_API_KEY`, the `httpx` package missing,
an API/timeout error, a malformed/empty diff, or a path-allowlist violation —
falls back to the DeterministicRunner. The loop therefore never hard-fails on the
Devin path, mirroring the Claude runner's contract.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from promptetheus.server.fix_agent import memory
from promptetheus.server.fix_agent.runner import (
    DEFAULT_ALLOWED_PATHS,
    _changed_paths,
    _path_inside,
)
from promptetheus.server.fix_agent.runners.deterministic import DeterministicRunner
from promptetheus.server.models import FixAgentResult

_DEFAULT_API_URL = "https://api.devin.ai"
_MAX_EVENTS = 24  # cap events injected into the prompt
#: Terminal Devin session states — stop polling once any of these is reached.
_TERMINAL_STATES: frozenset[str] = frozenset(
    {"exit", "error", "blocked", "finished", "suspended"}
)
#: status_detail values that mean the agent is done (v3 keeps status="running").
_TERMINAL_DETAILS: frozenset[str] = frozenset({"finished", "blocked", "suspended"})

#: JSON Schema (Draft 7) the Devin session must satisfy via provide_structured_output.
_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "diagnosis": {"type": "string"},
        "plan": {"type": "array", "items": {"type": "string"}},
        "diff": {"type": "string"},
    },
    "required": ["diagnosis", "plan", "diff"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are Promptetheus's fix agent running inside Devin. You receive a redacted "
    "incident bundle for a failed AI-agent run, plus verified fixes for similar past "
    "incidents as advanced context. Produce a concrete code fix as a unified diff. "
    "Constraints you MUST follow: (1) every file you touch MUST live under one of the "
    "allowed paths given in the bundle; (2) emit NEW-FILE diffs only — each file starts "
    "with `--- /dev/null` then `+++ b/<path>` then an `@@ -0,0 +1,N @@` hunk with every "
    "body line prefixed by `+`; (3) the fix must directly address the detected root "
    "cause — add the missing capability/guard that would have prevented the failure; "
    "(4) reuse what worked in the similar past fixes when applicable, but adapt rather "
    "than copy blindly. Return your answer via provide_structured_output with "
    "diagnosis, plan, and diff."
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except ValueError:
        return default


def _prompt(
    bundle: dict[str, Any],
    similar: list[dict[str, Any]],
    prior_critique: Any,
) -> str:
    incident = bundle.get("incident") or {}
    allowed = bundle.get("allowed_paths") or list(DEFAULT_ALLOWED_PATHS)
    events = (bundle.get("events") or [])[:_MAX_EVENTS]
    parts = [
        _SYSTEM,
        "",
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
    if similar:
        parts += [
            "",
            "## Advanced context — verified fixes for similar past incidents",
            "Adapt these proven remediations; do not copy blindly.",
            json.dumps(similar, default=str)[:6000],
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
    return "\n".join(parts)


class DevinRunner:
    """Real Devin fix runner with a deterministic fallback on any failure."""

    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        self.allowed_paths: list[str] = (
            list(allowed_paths) if allowed_paths else list(DEFAULT_ALLOWED_PATHS)
        )
        self.api_url = os.environ.get("PROMPTETHEUS_DEVIN_API_URL", _DEFAULT_API_URL).rstrip("/")
        # When set, drive the v3 org-scoped API (enterprise) instead of v1.
        self.org_id = (os.environ.get("PROMPTETHEUS_DEVIN_ORG_ID") or "").strip()
        self.poll_timeout = _env_int("PROMPTETHEUS_DEVIN_POLL_TIMEOUT", 600)
        self.poll_interval = _env_int("PROMPTETHEUS_DEVIN_POLL_INTERVAL", 10)

    def _sessions_path(self) -> str:
        if self.org_id:
            return f"/v3/organizations/{self.org_id}/sessions"
        return "/v1/sessions"

    def run(
        self,
        incident_bundle: dict[str, Any],
        *,
        prior_critique: Any = None,
        warm_start: Any = None,
    ) -> FixAgentResult:
        api_key = os.environ.get("DEVIN_API_KEY")
        if not api_key:
            return self._fallback(incident_bundle)
        try:
            import httpx
        except Exception:
            return self._fallback(incident_bundle)

        # Advanced context: surface several verified fixes for similar incidents.
        # `warm_start` (a single prior fix) is folded in when the loop supplies one.
        similar = memory.find_similar_fixes(incident_bundle)
        if warm_start and warm_start not in similar:
            similar = [warm_start, *similar]

        try:
            proposal = self._dispatch(httpx, api_key, incident_bundle, similar, prior_critique)
        except Exception:
            return self._fallback(incident_bundle)
        if proposal is None:
            return self._fallback(incident_bundle)

        diff = str(proposal.get("diff") or "").strip()
        if not diff:
            return self._fallback(incident_bundle)

        # Security Contract: reject any change outside the runner allow-list.
        changed = _changed_paths(diff)
        if not changed:
            return self._fallback(incident_bundle)
        for path in changed:
            if not _path_inside(path, self.allowed_paths):
                return self._fallback(incident_bundle)

        incident = incident_bundle.get("incident") or {}
        plan = [str(step) for step in (proposal.get("plan") or [])]
        diagnosis = str(proposal.get("diagnosis") or "") or "Devin-generated fix."
        return FixAgentResult(
            plan=plan or ["Apply the generated fix."],
            diff=diff if diff.endswith("\n") else diff + "\n",
            metadata={
                "fallback": False,
                "runner": "devin",
                "diagnosis": diagnosis,
                "allowed_paths": list(self.allowed_paths),
                "retry": prior_critique is not None,
                "session_id": proposal.get("_session_id"),
                "session_url": proposal.get("_session_url"),
                "similar_fix_count": len(similar),
                "similar_fix_ids": [s.get("from_incident_id") for s in similar],
            },
            summary=diagnosis,
            changed_files=changed,
            runner="devin",
            confidence=float(incident.get("confidence") or 0.0),
            evidence_refs=[
                int(e.get("seq"))
                for e in incident_bundle.get("events") or []
                if isinstance(e.get("seq"), int) and not isinstance(e.get("seq"), bool)
            ],
            fallback=False,
        )

    def _dispatch(
        self,
        httpx: Any,
        api_key: str,
        bundle: dict[str, Any],
        similar: list[dict[str, Any]],
        prior_critique: Any,
    ) -> dict[str, Any] | None:
        """Create + poll a Devin session, returning its structured output or None."""

        incident = bundle.get("incident") or {}
        headers = {"Authorization": f"Bearer {api_key}"}
        payload: dict[str, Any] = {
            "prompt": _prompt(bundle, similar, prior_critique),
            "idempotent": True,
            "structured_output_schema": _OUTPUT_SCHEMA,
            "tags": ["promptetheus", "fix-agent", str(incident.get("label") or "incident")],
            "title": f"Promptetheus fix: {incident.get('label') or incident.get('id')}",
        }
        max_acu = _env_int("PROMPTETHEUS_DEVIN_MAX_ACU", 0)
        if max_acu:
            payload["max_acu_limit"] = max_acu
        playbook = os.environ.get("PROMPTETHEUS_DEVIN_PLAYBOOK_ID")
        if playbook:
            payload["playbook_id"] = playbook

        sessions_path = self._sessions_path()
        with httpx.Client(base_url=self.api_url, headers=headers, timeout=30.0) as client:
            created = client.post(sessions_path, json=payload)
            created.raise_for_status()
            body = created.json()
            session_id = body.get("session_id")
            session_url = body.get("url")
            if not session_id:
                return None

            deadline = time.monotonic() + self.poll_timeout
            while time.monotonic() < deadline:
                detail = client.get(f"{sessions_path}/{session_id}")
                detail.raise_for_status()
                data = detail.json()
                output = data.get("structured_output")
                status = str(data.get("status") or "")
                detail_status = str(data.get("status_detail") or "")
                if isinstance(output, dict) and output.get("diff"):
                    output["_session_id"] = session_id
                    output["_session_url"] = session_url
                    return output
                if status in _TERMINAL_STATES or detail_status in _TERMINAL_DETAILS:
                    if isinstance(output, dict):
                        output["_session_id"] = session_id
                        output["_session_url"] = session_url
                        return output
                    return None
                time.sleep(self.poll_interval)
        return None

    def _fallback(self, incident_bundle: dict[str, Any]) -> FixAgentResult:
        return DeterministicRunner(allowed_paths=self.allowed_paths).run(incident_bundle)
