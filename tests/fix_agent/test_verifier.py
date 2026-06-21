"""Tests for the verification layer (LLM critique + regression gate).

The critique is the load-bearing gate in State-0 (regression is a deterministic
pass). It must: approve a good fix, reject a bad one, fail CLOSED on an API
error (never silently approve), and skip-approve only when no key is configured.
`verify()` combines both halves: passed == critique.approved AND after_fail==0.
"""

from __future__ import annotations

from types import SimpleNamespace

from promptetheus.server.fix_agent import verifier
from promptetheus.server.fix_agent.verifier import Critique, critique_fix, verify
from promptetheus.server.store import InMemoryStore

from .conftest import install_fake_anthropic


def _fix(diff: str = "--- /dev/null\n+++ b/agents/x.py\n@@ -0,0 +1 @@\n+x=1\n") -> SimpleNamespace:
    return SimpleNamespace(diff=diff, metadata={"diagnosis": "adds the missing guard"})


def _incident() -> dict:
    return {
        "id": "incident_1",
        "workspace_id": "ws_dev",
        "project_id": "proj_dev",
        "session_ids": ["sess_1"],
    }


def _bundle() -> dict:
    return {"root_cause": "selected the wrong slot", "incident": _incident()}


def test_critique_approves_good_fix(monkeypatch) -> None:
    parsed = verifier._CritiqueOut(approved=True, confidence=0.92, reason="addresses root cause")
    install_fake_anthropic(monkeypatch, parsed=parsed)

    critique = critique_fix(_bundle(), _fix())

    assert critique.approved is True
    assert critique.confidence == 0.92


def test_critique_rejects_bad_fix(monkeypatch) -> None:
    parsed = verifier._CritiqueOut(approved=False, confidence=0.1, reason="unrelated change")
    install_fake_anthropic(monkeypatch, parsed=parsed)

    critique = critique_fix(_bundle(), _fix())

    assert critique.approved is False
    assert "unrelated" in critique.reason


def test_critique_fails_closed_on_api_error(monkeypatch) -> None:
    install_fake_anthropic(monkeypatch, error=RuntimeError("boom"))

    critique = critique_fix(_bundle(), _fix())

    assert critique.approved is False  # never silently approve on error
    assert critique.confidence == 0.0


def test_critique_skips_when_no_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    critique = critique_fix(_bundle(), _fix())

    # Without a key, the critique steps aside so the deterministic demo still
    # closes the loop (regression remains the gate).
    assert critique.approved is True
    assert critique.confidence == 0.0


def test_verify_passes_when_both_gates_pass(monkeypatch) -> None:
    parsed = verifier._CritiqueOut(approved=True, confidence=0.9, reason="good")
    install_fake_anthropic(monkeypatch, parsed=parsed)
    store = InMemoryStore()

    record = verify(store, _incident(), _bundle(), _fix())

    assert record["passed"] is True
    assert record["regression_passed"] is True
    assert record["critique"]["approved"] is True


def test_verify_blocks_when_critique_rejects(monkeypatch) -> None:
    parsed = verifier._CritiqueOut(approved=False, confidence=0.2, reason="off-target")
    install_fake_anthropic(monkeypatch, parsed=parsed)
    store = InMemoryStore()

    record = verify(store, _incident(), _bundle(), _fix())

    # Regression passes in State-0, so the rejected critique is what blocks.
    assert record["regression_passed"] is True
    assert record["passed"] is False


def test_critique_as_dict_roundtrip() -> None:
    c = Critique(approved=True, confidence=0.5, reason="ok")
    assert c.as_dict() == {"approved": True, "confidence": 0.5, "reason": "ok"}
