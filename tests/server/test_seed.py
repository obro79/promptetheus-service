"""Test that scripts/seed.py runs and forms at least one incident.

Prefers importing the module's main() entry point (per the contract) over a
subprocess. main() drives the locked FastAPI contract through an in-process
TestClient and returns its process exit code; we assert it exits 0 and that
the seeded AcmeMeet failing-booking sessions cluster into >= 1 incident.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED_PATH = _REPO_ROOT / "scripts" / "seed.py"


def _load_seed_module() -> ModuleType:
    """Load scripts/seed.py as a standalone module by file path."""

    assert _SEED_PATH.is_file(), f"missing seed script at {_SEED_PATH}"
    spec = importlib.util.spec_from_file_location("promptetheus_seed_script", _SEED_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_main_exits_zero() -> None:
    seed = _load_seed_module()

    assert hasattr(seed, "main"), "seed.py must expose a main() entry point"

    exit_code = seed.main()

    assert exit_code == 0


def test_seed_forms_at_least_one_incident() -> None:
    seed = _load_seed_module()

    # Prefer the seed(client) helper so we can inspect the formed incidents
    # directly without parsing printed output.
    assert hasattr(seed, "seed"), "seed.py must expose a seed(client) helper"

    from fastapi.testclient import TestClient

    from promptetheus.server.app import create_app

    with TestClient(create_app()) as client:
        summary = seed.seed(client)

    assert summary["sessions_created"] >= 1
    assert summary["events_accepted"] >= 1
    assert summary["artifacts_created"] >= summary["sessions_created"]
    assert {"browser-agent", "support-agent", "coding-agent"} <= set(
        summary["agent_types"]
    )
    assert len(summary["incident_ids"]) >= 1
    assert summary["fix_agent_runs"] >= 1
    assert summary["regression_runs"] >= 1


def test_seed_uses_stable_artifact_ids_for_repeat_runs() -> None:
    seed = _load_seed_module()

    from fastapi.testclient import TestClient

    from promptetheus.server.app import create_app

    app = create_app()
    with TestClient(app) as client:
        first = seed.seed(client, run_workflows=False)
        second = seed.seed(client, run_workflows=False)

    assert first["artifacts_created"] == second["artifacts_created"]
    artifact_ids = list(app.state.store._artifacts.keys())  # noqa: SLF001
    assert len(artifact_ids) == first["artifacts_created"]
    assert len(artifact_ids) == len(set(artifact_ids))
