"""Tests for the Claude-backed fix runner.

The runner must (1) return a real `runner="claude"` result on a well-formed,
in-allowlist diff, and (2) fall back to the deterministic runner — never
hard-fail — on every failure mode: no API key, an empty/malformed diff, a diff
that escapes the allowed paths, or an `anthropic` API error. The deterministic
fallback always yields a usable `runner="deterministic", fallback=True` result.
"""

from __future__ import annotations

from promptetheus.server.fix_agent.runners.claude import ClaudeRunner, FixProposal

from .conftest import install_fake_anthropic, new_file_diff


def _bundle(allowed_paths: list[str] | None = None) -> dict:
    bundle: dict = {
        "incident": {
            "id": "incident_1",
            "workspace_id": "ws_dev",
            "project_id": "proj_dev",
            "label": "browser_goal_mismatch",
            "severity": "high",
            "confidence": 0.91,
        },
        "user_goal": "Book a 30 minute AcmeMeet with Dana on Tuesday at 2pm",
        "root_cause": "The booking step selected the wrong slot.",
        "source": "browserbase",
        "events": [{"seq": 3}, {"seq": 5}],
    }
    if allowed_paths is not None:
        bundle["allowed_paths"] = allowed_paths
    return bundle


def test_returns_claude_result_on_valid_in_allowlist_diff(monkeypatch) -> None:
    proposal = FixProposal(
        diagnosis="Add a post-action slot verification guard.",
        plan=["Add guard", "Re-run booking"],
        diff=new_file_diff("agents/guard.py"),
    )
    calls = install_fake_anthropic(monkeypatch, parsed=proposal)

    runner = ClaudeRunner(allowed_paths=["agents/"])
    result = runner.run(_bundle(allowed_paths=["agents/"]))

    assert result.runner == "claude"
    assert result.fallback is False
    assert result.metadata["fallback"] is False
    assert result.metadata["diagnosis"] == proposal.diagnosis
    assert "agents/guard.py" in result.changed_files
    assert result.diff.endswith("\n")
    # Called Claude with the configured model + structured output + adaptive thinking.
    assert len(calls) == 1
    assert calls[0]["model"] == "claude-opus-4-8"
    assert calls[0]["output_format"] is FixProposal
    assert calls[0]["thinking"] == {"type": "adaptive"}


def test_falls_back_when_no_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runner = ClaudeRunner(allowed_paths=["agents/"])

    result = runner.run(_bundle())

    assert result.runner == "deterministic"
    assert result.fallback is True
    assert result.diff  # the deterministic runner always produces a usable diff


def test_falls_back_on_empty_diff(monkeypatch) -> None:
    proposal = FixProposal(diagnosis="d", plan=["p"], diff="   ")
    install_fake_anthropic(monkeypatch, parsed=proposal)

    result = ClaudeRunner(allowed_paths=["agents/"]).run(_bundle())

    assert result.runner == "deterministic"
    assert result.fallback is True


def test_falls_back_on_path_escape(monkeypatch) -> None:
    # A syntactically valid diff that escapes the allow-list must NOT ship.
    proposal = FixProposal(
        diagnosis="d", plan=["p"], diff=new_file_diff("infra/secrets/leak.py")
    )
    install_fake_anthropic(monkeypatch, parsed=proposal)

    result = ClaudeRunner(allowed_paths=["agents/"]).run(_bundle(allowed_paths=["agents/"]))

    assert result.runner == "deterministic"
    assert result.fallback is True
    assert all("infra/secrets" not in p for p in result.changed_files)


def test_falls_back_on_api_error(monkeypatch) -> None:
    install_fake_anthropic(monkeypatch, error=RuntimeError("anthropic 503"))

    result = ClaudeRunner(allowed_paths=["agents/"]).run(_bundle())

    assert result.runner == "deterministic"
    assert result.fallback is True
