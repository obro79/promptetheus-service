"""Tests for the bounded self-healing loop.

The loop must: open a PR and STOP on the first verified attempt, retry with the
prior critique when the first attempt is rejected, escalate after the attempt
budget is exhausted, thread the incident `source` end-to-end onto the report,
and audit every attempt. No API key is set, so the Claude runner falls back to
the deterministic runner — the loop itself never depends on the network.
"""

from __future__ import annotations

import pytest

from promptetheus.server.fix_agent import loop as loop_mod
from promptetheus.server.fix_agent.loop import heal_incident
from promptetheus.server.store import InMemoryStore


@pytest.fixture(autouse=True)
def _no_anthropic(monkeypatch):
    # Force the deterministic runner + the no-key critique-skip path so the loop
    # is hermetic. Individual tests override `verify` to control the gate.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)


def _incident(source: str | None = None) -> dict:
    incident = {
        "id": "incident_1",
        "workspace_id": "ws_dev",
        "project_id": "proj_dev",
        "label": "browser_goal_mismatch",
        "severity": "high",
        "confidence": 0.9,
        "session_ids": ["sess_1"],
    }
    if source is not None:
        incident["source"] = source
    return incident


def _record(passed: bool, reason: str = "") -> dict:
    return {
        "passed": passed,
        "critique": {"approved": passed, "confidence": 0.9 if passed else 0.1, "reason": reason},
        "regression": {"after_pass": 1, "after_fail": 0, "before_fail": 1},
        "regression_passed": True,
    }


def test_pr_opened_on_first_verified_attempt() -> None:
    store = InMemoryStore()
    report = heal_incident(store, _incident(source="browserbase"))

    assert report.status == "pr_opened"
    assert report.attempts == 1
    assert report.source == "browserbase"
    assert report.pr is not None
    assert len(report.trail) == 1
    # The incident was finalized + the attempt was audited.
    audits = [a["action"] for a in store.list_audit(workspace_id="ws_dev")]
    assert "heal_attempt" in audits
    assert "github_pr_create" in audits


def test_succeeds_on_retry_after_first_rejection(monkeypatch) -> None:
    store = InMemoryStore()
    outcomes = iter([_record(False, "off-target"), _record(True, "fixed")])
    monkeypatch.setattr(loop_mod, "verify", lambda *a, **k: next(outcomes))

    report = heal_incident(store, _incident(), max_attempts=3)

    assert report.status == "pr_opened"
    assert report.attempts == 2
    assert len(report.trail) == 2
    assert report.trail[0]["passed"] is False
    assert report.trail[1]["passed"] is True


def test_escalates_after_max_attempts(monkeypatch) -> None:
    store = InMemoryStore()
    monkeypatch.setattr(loop_mod, "verify", lambda *a, **k: _record(False, "still broken"))

    report = heal_incident(store, _incident(), max_attempts=2)

    assert report.status == "escalated"
    assert report.attempts == 2
    assert report.reason == "max_attempts"
    assert report.pr is None
    assert len(report.trail) == 2


def test_source_defaults_to_unknown_when_absent() -> None:
    store = InMemoryStore()
    report = heal_incident(store, _incident())
    assert report.source == "unknown"


def test_warm_start_from_memory_is_passed_to_first_attempt(monkeypatch) -> None:
    store = InMemoryStore()
    seen: dict = {}

    def _fake_run(self, bundle, *, prior_critique=None, warm_start=None):
        seen["warm_start"] = warm_start
        from promptetheus.server.fix_agent.runners.deterministic import DeterministicRunner

        return DeterministicRunner(allowed_paths=bundle.get("allowed_paths")).run(bundle)

    monkeypatch.setattr(loop_mod.ClaudeRunner, "run", _fake_run)
    monkeypatch.setattr(
        loop_mod.memory, "find_similar_fix", lambda bundle: {"from_incident_id": "old", "score": 0.9}
    )

    report = heal_incident(store, _incident())

    assert report.status == "pr_opened"
    assert seen["warm_start"] == {"from_incident_id": "old", "score": 0.9}
