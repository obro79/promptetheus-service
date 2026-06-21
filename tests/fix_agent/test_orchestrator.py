"""Tests for the orchestrator seam.

`run_loop` defaults to the in-process loop and tags the report `inprocess`.
Selecting `agentspan` runs the heal inside a real Agentspan execution (faked
here) and stamps the execution id (`AgentResult.workflow_id`) onto the report.
When the Agentspan SDK is absent it must fall back to in-process so the demo
never depends on the Orkes/Agentspan booth.
"""

from __future__ import annotations

import sys
import types

import pytest

from promptetheus.server.fix_agent.orchestrator import _mode, run_loop
from promptetheus.server.store import InMemoryStore


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)


def _incident() -> dict:
    return {
        "id": "incident_1",
        "workspace_id": "ws_dev",
        "project_id": "proj_dev",
        "label": "browser_goal_mismatch",
        "confidence": 0.9,
        "session_ids": ["sess_1"],
        "source": "lambda",
    }


def _install_fake_agentspan(
    monkeypatch,
    *,
    workflow_id: str,
    call_tool: bool = True,
    id_attr: str = "workflow_id",
) -> None:
    """Inject a minimal fake `agentspan.agents` matching the documented API.

    `id_attr` lets a test choose whether the result exposes the documented
    `workflow_id` or the `execution_id` the real runtime actually logs.
    """

    agents = types.ModuleType("agentspan.agents")

    def tool(fn):  # passthrough decorator (real one wraps with a schema)
        return fn

    class _Result:
        def __init__(self, wid: str) -> None:
            setattr(self, id_attr, wid)  # workflow_id (docs) or execution_id (runtime)

    class Agent:
        def __init__(self, **kwargs) -> None:
            self.tools = kwargs.get("tools") or []

    class AgentRuntime:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def run(self, agent, prompt):
            if call_tool:  # the LLM agent decides to call the heal tool
                for fn in agent.tools:
                    fn("incident_1")
            return _Result(workflow_id)

    agents.tool = tool
    agents.Agent = Agent
    agents.AgentRuntime = AgentRuntime

    pkg = types.ModuleType("agentspan")
    pkg.agents = agents
    monkeypatch.setitem(sys.modules, "agentspan", pkg)
    monkeypatch.setitem(sys.modules, "agentspan.agents", agents)


def test_default_mode_is_inprocess() -> None:
    assert _mode(None) == "inprocess"
    assert _mode("AgentSpan") == "agentspan"
    assert _mode("garbage") == "inprocess"


def test_run_loop_inprocess() -> None:
    store = InMemoryStore()
    report = run_loop(store, _incident())

    assert report.status == "pr_opened"
    assert report.orchestrator == "inprocess"
    assert report.workflow_run_id is None
    assert report.source == "lambda"


def test_agentspan_runs_and_stamps_execution_id(monkeypatch) -> None:
    _install_fake_agentspan(monkeypatch, workflow_id="exec-xyz")
    store = InMemoryStore()

    report = run_loop(store, _incident(), mode="agentspan")

    assert report.orchestrator == "agentspan"
    assert report.workflow_run_id == "exec-xyz"
    assert report.status == "pr_opened"
    assert report.source == "lambda"


def test_agentspan_reads_execution_id_attribute(monkeypatch) -> None:
    # The real runtime exposes the trackable id as `execution_id`, not `workflow_id`.
    _install_fake_agentspan(monkeypatch, workflow_id="exec-runtime", id_attr="execution_id")
    store = InMemoryStore()

    report = run_loop(store, _incident(), mode="agentspan")

    assert report.orchestrator == "agentspan"
    assert report.workflow_run_id == "exec-runtime"


def test_agentspan_heals_even_if_agent_skips_tool(monkeypatch) -> None:
    # If the LLM never calls the heal tool, the deterministic loop still runs so
    # the agentspan path is never weaker than in-process.
    _install_fake_agentspan(monkeypatch, workflow_id="exec-2", call_tool=False)
    store = InMemoryStore()

    report = run_loop(store, _incident(), mode="agentspan")

    assert report.orchestrator == "agentspan"
    assert report.workflow_run_id == "exec-2"
    assert report.status == "pr_opened"


def test_agentspan_without_sdk_falls_back_to_inprocess(monkeypatch) -> None:
    # Simulate the SDK being absent (block both the package and submodule) ->
    # import fails -> the loop runs in-process and the demo never depends on it.
    monkeypatch.setitem(sys.modules, "agentspan", None)
    monkeypatch.setitem(sys.modules, "agentspan.agents", None)
    store = InMemoryStore()

    report = run_loop(store, _incident(), mode="agentspan")

    assert report.status == "pr_opened"
    assert report.orchestrator == "inprocess"
    assert report.workflow_run_id is None
