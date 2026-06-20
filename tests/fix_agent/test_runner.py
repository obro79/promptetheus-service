"""Tests for the fix-agent runner: fallback diff shape, path allowlist, redaction.

These exercise the State-0 FixAgentRunner and build_incident_bundle
against the frozen server/fix_agent/runner.py contract:

- run emits a well-formed unified diff (--- /+++ /@@) confined to
  allowed_paths.
- a generated change outside allowed_paths raises ValueError.
- build_incident_bundle redacts secrets / cookies / auth headers from event
  payloads (a planted secret must not survive into the bundle).
"""

from __future__ import annotations

import json

import pytest

from promptetheus.server.fix_agent.runner import (
    DEFAULT_ALLOWED_PATHS,
    FixAgentRunner,
    build_incident_bundle,
)
from promptetheus.server.store import InMemoryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bundle(allowed_paths: list[str] | None = None) -> dict:
    """Minimal incident bundle the runner accepts."""

    bundle: dict = {
        "incident": {
            "id": "incident_ws_dev_browser_goal_mismatch",
            "workspace_id": "ws_dev",
            "project_id": "proj_dev",
            "label": "browser_goal_mismatch",
            "severity": "high",
            "status": "new",
            "confidence": 0.9,
            "session_count": 2,
        },
        "representative_session_id": "sess_1",
        "user_goal": "Book a 30 minute AcmeMeet with Dana on Tuesday at 2pm",
        "critical_step_seq": 3,
        "root_cause": "The booking step selected the wrong slot.",
        "events": [],
    }
    if allowed_paths is not None:
        bundle["allowed_paths"] = allowed_paths
    return bundle


# ---------------------------------------------------------------------------
# Diff well-formedness + allowlist confinement
# ---------------------------------------------------------------------------


def test_run_produces_well_formed_unified_diff() -> None:
    runner = FixAgentRunner()

    result = runner.run(_bundle())

    diff = result.diff
    assert isinstance(diff, str) and diff
    lines = diff.splitlines()

    # Unified-diff headers + at least one hunk header are present.
    assert any(line.startswith("--- ") for line in lines), diff
    plus_headers = [line for line in lines if line.startswith("+++ ")]
    assert plus_headers, diff
    assert any(line.startswith("@@") for line in lines), diff

    # The destination header uses the b/<path> convention.
    target_header = plus_headers[0]
    assert target_header.startswith("+++ b/"), target_header

    # Fallback metadata is stamped as the contract requires.
    assert result.metadata["fallback"] is True
    assert result.metadata["allowed_paths"] == list(DEFAULT_ALLOWED_PATHS)
    assert result.metadata["branch"].startswith("promptetheus/")
    assert result.plan  # a non-empty plan


def test_run_diff_is_confined_to_allowed_paths() -> None:
    runner = FixAgentRunner(allowed_paths=["agents/"])

    result = runner.run(_bundle())

    target = result.diff.splitlines()[1]  # +++ b/<path>
    assert target.startswith("+++ b/agents/"), target


def test_run_rejects_change_outside_allowed_paths() -> None:
    # The runner allow-list is the hard boundary. The bundle requests a guard in
    # infra/ which is outside the runner's agents/ allow-list, so run
    # must reject it rather than silently rewriting the path.
    runner = FixAgentRunner(allowed_paths=["agents/"])

    with pytest.raises(ValueError):
        runner.run(_bundle(allowed_paths=["infra/secrets/"]))


def test_run_rejects_path_traversal_request() -> None:
    runner = FixAgentRunner(allowed_paths=["agents/"])

    with pytest.raises(ValueError):
        runner.run(_bundle(allowed_paths=["../etc/"]))


# ---------------------------------------------------------------------------
# Bundle redaction
# ---------------------------------------------------------------------------


def _flatten(value: object) -> str:
    """Serialize an arbitrary structure to a single searchable string."""

    return json.dumps(value, default=str)


def test_build_incident_bundle_redacts_secrets_and_cookies() -> None:
    store = InMemoryStore()
    planted_secret = "pt_super_secret_value_42"
    planted_cookie = "session=ABCDEF123456; HttpOnly"
    planted_bearer = "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"

    store.create_session(
        {
            "id": "sess_1",
            "workspace_id": "ws_dev",
            "project_id": "proj_dev",
            "user_goal": "Book a 30 minute AcmeMeet with Dana on Tuesday at 2pm",
        }
    )
    # An event whose payload carries sensitive keys + an inline bearer token.
    store.append_event(
        "sess_1",
        {
            "type": "browser_action",
            "session_id": "sess_1",
            "timestamp": "2026-06-12T09:00:03+00:00",
            "seq": 3,
            "idempotency_key": "sess_1-3",
            "payload": {
                "action": "submit",
                "target": "#confirm-booking",
                "api_key": planted_secret,
                "headers": {
                    "cookie": planted_cookie,
                    "authorization": planted_bearer,
                    "note": f"called with {planted_bearer}",
                },
            },
            "metadata": {"access_token": planted_secret},
        },
    )
    store.set_analysis(
        "sess_1",
        {"root_cause": "The booking step selected the wrong slot."},
    )

    incident = {
        "id": "incident_ws_dev_browser_goal_mismatch",
        "workspace_id": "ws_dev",
        "project_id": "proj_dev",
        "label": "browser_goal_mismatch",
        "severity": "high",
        "status": "new",
        "confidence": 0.9,
        "representative_session_id": "sess_1",
        "session_ids": ["sess_1"],
        "critical_step_seq": 3,
    }

    bundle = build_incident_bundle(store, incident)

    serialized = _flatten(bundle["events"])
    # The planted secrets / cookie / bearer token must be gone.
    assert planted_secret not in serialized
    assert "session=ABCDEF123456" not in serialized
    assert "eyJhbGciOiJIUzI1NiJ9" not in serialized
    assert "[REDACTED]" in serialized

    # The bundle still carries the non-sensitive context it needs.
    assert bundle["root_cause"] == "The booking step selected the wrong slot."
    assert bundle["user_goal"].startswith("Book a 30 minute AcmeMeet")
    assert bundle["critical_step_seq"] == 3
    assert bundle["allowed_paths"]  # defaulted when the incident has none
