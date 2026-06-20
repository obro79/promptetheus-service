"""Regression runner: produce a before/after pass/fail row for an incident.

State-0 ships a deterministic fallback (no live replay): the fix is assumed to
flip every affected session from failing to passing. The runner builds a
regression_run row, persists it through store.add_regression_run, and
returns the stored row.
"""

from __future__ import annotations

import json
from typing import Any

from promptetheus.server.store import Store


def run_regression(
    store: Store,
    incident: dict[str, Any],
    *,
    pr_url: str | None = None,
    fallback_profile: str | None = None,
) -> dict[str, Any]:
    """Produce and persist a regression_run row for incident.

    State-0 deterministic fallback: N = max(1, len(session_ids)); before is
    pass 0 / fail N and after is pass N / fail 0 (the candidate fix is
    assumed to resolve every affected session). The row is persisted via
    store.add_regression_run and the stored row is returned.

    Args:
        store: Persistence interface (the canonical write gateway).
        incident: The incident row being regression-tested.
        pr_url: Optional pull-request URL associated with the fix under test.
        fallback_profile: Optional deterministic profile for demo dry-runs.

    Returns:
        The stored regression_run row.
    """

    session_ids = list(incident.get("session_ids") or [])
    n = max(1, len(session_ids))
    profile = (fallback_profile or "state0").strip().lower()

    before_pass = 0
    before_fail = n
    if profile == "demo":
        after_fail = 1 if n > 1 else 0
        after_pass = n - after_fail
        user_confirm_count = min(2, after_pass)
    else:
        after_pass = n
        after_fail = 0
        user_confirm_count = 0

    replay_rows = [
        {
            "session_id": session_id,
            "before": "fail",
            "after": "fail" if index >= after_pass else "pass",
        }
        for index, session_id in enumerate(session_ids or ["synthetic_session"])
    ]

    raw_results = {
        "fallback": True,
        "fallback_profile": profile,
        "replay_mode": "deterministic_scripted",
        "session_ids": session_ids,
        "before": {"pass": before_pass, "fail": before_fail},
        "after": {"pass": after_pass, "fail": after_fail},
        "user_confirm_count": user_confirm_count,
        "rows": replay_rows,
    }

    run = {
        "workspace_id": incident.get("workspace_id"),
        "project_id": incident.get("project_id"),
        "incident_id": incident.get("id"),
        "pr_url": pr_url,
        "before_pass": before_pass,
        "before_fail": before_fail,
        "after_pass": after_pass,
        "after_fail": after_fail,
        "user_confirm_count": user_confirm_count,
        "raw_results_json": json.dumps(raw_results),
        "fallback": True,
    }

    return store.add_regression_run(run)
