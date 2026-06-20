"""Tests for the regression runner: before/after row shape + persistence.

Exercises the State-0 deterministic fallback in server/regression/runner.py:
before is pass 0 / fail N and after is pass N / fail 0 where
N = max(1, len(incident.session_ids)). The row is fallback=True and is
retrievable through store.list_regression_runs.
"""

from __future__ import annotations

import json

from promptetheus.server.regression.runner import run_regression
from promptetheus.server.store import InMemoryStore


def _incident(session_ids: list[str]) -> dict:
    return {
        "id": "incident_ws_dev_browser_goal_mismatch",
        "workspace_id": "ws_dev",
        "project_id": "proj_dev",
        "label": "browser_goal_mismatch",
        "session_ids": session_ids,
    }


def test_run_regression_before_after_counts_and_fallback() -> None:
    store = InMemoryStore()
    incident = _incident(["sess_1", "sess_2", "sess_3"])
    n = len(incident["session_ids"])

    run = run_regression(store, incident)

    # before = pass 0 / fail N ; after = pass N / fail 0
    assert run["before_pass"] == 0
    assert run["before_fail"] == n
    assert run["after_pass"] == n
    assert run["after_fail"] == 0

    assert run["fallback"] is True
    assert run["user_confirm_count"] == 0
    assert run["incident_id"] == incident["id"]
    assert run["workspace_id"] == "ws_dev"
    assert run["project_id"] == "proj_dev"
    assert run["pr_url"] is None
    assert "id" in run  # stamped by the store on persist

    # raw_results_json round-trips and mirrors the before/after counts.
    raw = json.loads(run["raw_results_json"])
    assert raw["fallback"] is True
    assert raw["before"] == {"pass": 0, "fail": n}
    assert raw["after"] == {"pass": n, "fail": 0}


def test_run_regression_persists_and_is_retrievable() -> None:
    store = InMemoryStore()
    incident = _incident(["sess_1", "sess_2"])

    run = run_regression(store, incident, pr_url="https://github.com/acme/repo/pull/7")

    stored = store.list_regression_runs(incident["id"])
    assert len(stored) == 1
    assert stored[0]["id"] == run["id"]
    assert stored[0]["pr_url"] == "https://github.com/acme/repo/pull/7"
    assert stored[0]["before_fail"] == 2
    assert stored[0]["after_pass"] == 2


def test_run_regression_minimum_n_of_one_with_no_sessions() -> None:
    store = InMemoryStore()
    incident = _incident([])

    run = run_regression(store, incident)

    # N floors at 1 even when the incident has no session_ids.
    assert run["before_fail"] == 1
    assert run["after_pass"] == 1
    assert run["before_pass"] == 0
    assert run["after_fail"] == 0


def test_run_regression_demo_profile_is_labeled_and_not_perfect() -> None:
    store = InMemoryStore()
    incident = _incident(["sess_1", "sess_2", "sess_3"])

    run = run_regression(store, incident, fallback_profile="demo")

    assert run["before_fail"] == 3
    assert run["after_pass"] == 2
    assert run["after_fail"] == 1
    assert run["user_confirm_count"] == 2

    raw = json.loads(run["raw_results_json"])
    assert raw["fallback_profile"] == "demo"
    assert raw["replay_mode"] == "deterministic_scripted"
    assert [row["after"] for row in raw["rows"]] == ["pass", "pass", "fail"]
