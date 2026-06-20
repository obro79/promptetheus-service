from __future__ import annotations

from typing import Any

import pytest

from promptetheus.server.fix_agent.runner import FixAgentRunner
from promptetheus.server.github import GitHubConfig, create_pull_request


def _fix_result() -> Any:
    bundle = {
        "incident": {
            "id": "incident_ws_dev_browser_goal_mismatch",
            "label": "browser_goal_mismatch",
            "confidence": 0.9,
        },
        "allowed_paths": ["agents/"],
        "events": [{"seq": 3}],
    }
    return FixAgentRunner(allowed_paths=["agents/"]).run(bundle)


def _incident() -> dict[str, Any]:
    return {
        "id": "incident_ws_dev_browser_goal_mismatch",
        "label": "browser_goal_mismatch",
        "workspace_id": "ws_dev",
        "project_id": "proj_dev",
    }


def _bundle() -> dict[str, Any]:
    return {
        "representative_session_id": "sess_1",
        "root_cause": "The browser selected the wrong slot.",
        "regression_case": {"id": "regrun_1"},
        "allowed_paths": ["agents/"],
    }


class FakeGitHubTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((method, path, json_body))
        if path.endswith("/access_tokens"):
            return {"token": "installation-token"}
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "base-sha"}}
        if path.endswith("/git/refs"):
            return {"ref": "refs/heads/promptetheus/demo"}
        if "/contents/" in path:
            return {"content": {"path": path.rsplit("/contents/", 1)[1]}}
        if path.endswith("/pulls"):
            return {"html_url": "https://github.com/acme/repo/pull/7"}
        raise AssertionError(f"unexpected GitHub path: {path}")


def test_create_pull_request_uses_mockable_github_transport() -> None:
    transport = FakeGitHubTransport()
    config = GitHubConfig(
        app_id="1",
        private_key="test-private-key",
        installation_id="123",
        repo="acme/repo",
        allowed_paths=["agents/"],
        enabled=True,
    )

    result = create_pull_request(
        fix_result=_fix_result(),
        incident=_incident(),
        bundle=_bundle(),
        config=config,
        transport=transport,
    )

    assert result is not None
    assert result.fallback is False
    assert result.pr_url == "https://github.com/acme/repo/pull/7"
    assert result.branch.startswith("promptetheus/incident_ws_dev_browser_goal_mismatch")
    assert result.changed_files == ["agents/goal_verification_guard.py"]
    assert any(path.endswith("/pulls") for _, path, _ in transport.calls)
    assert any("/contents/agents/goal_verification_guard.py" in path for _, path, _ in transport.calls)


def test_create_pull_request_returns_labeled_fallback_preview() -> None:
    config = GitHubConfig(
        repo="acme/repo",
        allowed_paths=["agents/"],
        enabled=True,
        fallback=True,
    )

    result = create_pull_request(
        fix_result=_fix_result(),
        incident=_incident(),
        bundle=_bundle(),
        config=config,
    )

    assert result is not None
    assert result.fallback is True
    assert result.pr_url is None
    assert "PROMPTETHEUS_GITHUB_FALLBACK" in result.metadata["fallback_reason"]
    assert "Root cause" in result.body


def test_create_pull_request_rejects_out_of_allowlist_diff() -> None:
    fix_result = _fix_result()
    fix_result.diff = "--- /dev/null\n+++ b/infra/secrets.py\n@@ -0,0 +1 @@\n+SECRET = 'x'\n"

    with pytest.raises(ValueError):
        create_pull_request(
            fix_result=fix_result,
            incident=_incident(),
            bundle=_bundle(),
            config=GitHubConfig(enabled=True, fallback=True, allowed_paths=["agents/"]),
        )
