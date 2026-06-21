"""Tests for the Redis fix-memory + heal-timeline module.

Every function must degrade to a safe no-op when `REDIS_URL` is unset (the test
and local-dev default) so the loop is unaffected by Redis being absent. When a
client IS available, errors inside it must be swallowed — memory failures can
never break remediation.
"""

from __future__ import annotations

import pytest

from promptetheus.server.fix_agent import memory


@pytest.fixture(autouse=True)
def _reset_memory_client(monkeypatch):
    # The module caches its client; reset between tests so env changes take.
    monkeypatch.setattr(memory, "_client", None, raising=False)
    monkeypatch.setattr(memory, "_client_resolved", False, raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)


def _bundle() -> dict:
    return {
        "incident": {"id": "incident_1", "workspace_id": "ws_dev", "label": "goal_mismatch"},
        "root_cause": "selected the wrong slot",
    }


def test_find_similar_fix_is_noop_without_redis() -> None:
    assert memory.find_similar_fix(_bundle()) is None


def test_remember_fix_is_noop_without_redis() -> None:
    # Must not raise even though there is no Redis backing it.
    memory.remember_fix(_bundle()["incident"], _bundle(), object())


def test_timeline_publish_and_read_noop_without_redis() -> None:
    memory.timeline_publish("incident_1", {"kind": "attempt", "attempt": 1})
    assert memory.timeline_read("incident_1") == []


def test_redis_errors_are_swallowed(monkeypatch) -> None:
    class _Boom:
        def smembers(self, *a, **k):
            raise RuntimeError("redis down")

        def xadd(self, *a, **k):
            raise RuntimeError("redis down")

        def xrange(self, *a, **k):
            raise RuntimeError("redis down")

    monkeypatch.setattr(memory, "_client", _Boom(), raising=False)
    monkeypatch.setattr(memory, "_client_resolved", True, raising=False)

    # A failing client must not propagate out of any public function.
    assert memory.find_similar_fix(_bundle()) is None
    memory.timeline_publish("incident_1", {"kind": "attempt"})
    assert memory.timeline_read("incident_1") == []


def test_lexical_similarity_scoring() -> None:
    # Pure helper: token-overlap similarity, used as the no-embedder fallback.
    assert memory._lexical("wrong slot booking", "wrong slot booking") == pytest.approx(1.0)
    assert memory._lexical("alpha beta", "gamma delta") == 0.0
