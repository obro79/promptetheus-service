"""Tests for the Redis fix-memory + heal-timeline module.

Every function must degrade to a safe no-op when `REDIS_URL` is unset (the test
and local-dev default) so the loop is unaffected by Redis being absent. When a
client IS available, errors inside it must be swallowed — memory failures can
never break remediation.
"""

from __future__ import annotations

import json

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


class _FakeRedis:
    """Minimal in-memory stand-in for the redis client surface memory.py uses."""

    def __init__(self, vsim: list | None = None) -> None:
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.commands: list[tuple] = []
        self._vsim = vsim or []

    def get(self, key: str):
        return self.kv.get(key)

    def set(self, key: str, value: str) -> None:
        self.kv[key] = value

    def sadd(self, key: str, *vals: str) -> None:
        self.sets.setdefault(key, set()).update(vals)

    def smembers(self, key: str):
        return self.sets.get(key, set())

    def execute_command(self, *args):
        self.commands.append(args)
        if args and args[0] == "VSIM":
            return self._vsim
        return None


def _install(monkeypatch, client) -> None:
    monkeypatch.setattr(memory, "_client", client, raising=False)
    monkeypatch.setattr(memory, "_client_resolved", True, raising=False)


def _query_bundle() -> dict:
    return {
        "incident": {"id": "incident_new", "workspace_id": "ws_dev", "label": "goal_mismatch"},
        "root_cause": "selected the wrong slot",
    }


def _store_row(client: _FakeRedis, ws: str, fix_id: str, signature: str, embedding=None) -> None:
    client.kv[f"ptfix:{ws}:{fix_id}"] = json.dumps(
        {
            "incident_id": fix_id,
            "label": "goal_mismatch",
            "signature": signature,
            "diff": f"--- /dev/null\n+++ b/agents/{fix_id}.py\n@@ -0,0 +1,1 @@\n+pass\n",
            "plan": ["step"],
            "embedding": embedding,
        }
    )
    client.sets.setdefault(f"ptfix:ids:{ws}", set()).add(fix_id)


def test_fallback_scan_ranks_by_lexical_overlap(monkeypatch) -> None:
    client = _FakeRedis()
    _store_row(client, "ws_dev", "old_match", "goal_mismatch selected the wrong slot")
    _store_row(client, "ws_dev", "old_unrelated", "alpha beta gamma delta")
    _install(monkeypatch, client)

    matches = memory.find_similar_fixes(_query_bundle(), limit=3)

    assert [m["from_incident_id"] for m in matches] == ["old_match"]
    assert memory.find_similar_fix(_query_bundle())["from_incident_id"] == "old_match"


def test_vector_path_uses_vsim_and_excludes_self(monkeypatch) -> None:
    # VSIM returns the query incident itself + two neighbors; self is dropped and
    # the rest are ranked by their similarity scores.
    client = _FakeRedis(vsim=["incident_new", "1.0", "old_a", "0.95", "old_b", "0.81"])
    _store_row(client, "ws_dev", "old_a", "a", embedding=[1.0, 0.0])
    _store_row(client, "ws_dev", "old_b", "b", embedding=[0.0, 1.0])
    _install(monkeypatch, client)
    monkeypatch.setenv("VOYAGE_API_KEY", "x")
    monkeypatch.setattr(memory, "_embed", lambda text: [1.0, 0.0])

    matches = memory.find_similar_fixes(_query_bundle(), limit=5)

    assert [m["from_incident_id"] for m in matches] == ["old_a", "old_b"]
    assert any(cmd[0] == "VSIM" for cmd in client.commands)


def test_remember_fix_indexes_into_vector_set(monkeypatch) -> None:
    client = _FakeRedis()
    _install(monkeypatch, client)
    monkeypatch.setenv("VOYAGE_API_KEY", "x")
    monkeypatch.setattr(memory, "_embed", lambda text: [0.1, 0.2, 0.3])

    class _Fix:
        diff = "--- /dev/null\n+++ b/agents/x.py\n@@ -0,0 +1,1 @@\n+pass\n"
        plan = ["step"]

    memory.remember_fix(_query_bundle()["incident"], _query_bundle(), _Fix())

    assert any(cmd[0] == "VADD" for cmd in client.commands)
    assert client.kv.get("ptfix:ws_dev:incident_new") is not None


def test_find_similar_fixes_respects_limit_and_noop_without_redis() -> None:
    assert memory.find_similar_fixes(_query_bundle()) == []
    assert memory.find_similar_fixes(_query_bundle(), limit=0) == []


def _store_labeled(client: _FakeRedis, ws: str, fix_id: str, label: str) -> None:
    client.kv[f"ptfix:{ws}:{fix_id}"] = json.dumps(
        {"incident_id": fix_id, "label": label, "signature": label, "embedding": [1.0, 0.0]}
    )
    client.sets.setdefault(f"ptfix:ids:{ws}", set()).add(fix_id)


def test_cluster_incident_is_noop_without_redis() -> None:
    assert memory.cluster_incident(_query_bundle()) is None


def test_cluster_incident_knn_majority_vote(monkeypatch) -> None:
    # VSIM returns the incident itself (excluded) + three neighbours: two label
    # "goal_mismatch" and one "ignored_warning". KNN vote -> goal_mismatch.
    client = _FakeRedis(
        vsim=["incident_new", "1.0", "old_a", "0.95", "old_b", "0.90", "old_c", "0.85"]
    )
    _store_labeled(client, "ws_dev", "old_a", "goal_mismatch")
    _store_labeled(client, "ws_dev", "old_b", "goal_mismatch")
    _store_labeled(client, "ws_dev", "old_c", "ignored_warning")
    _install(monkeypatch, client)
    monkeypatch.setenv("VOYAGE_API_KEY", "x")
    monkeypatch.setattr(memory, "_embed", lambda text: [1.0, 0.0])

    cluster = memory.cluster_incident(_query_bundle())

    assert cluster is not None
    assert cluster["label"] == "goal_mismatch"
    assert cluster["size"] == 3
    assert cluster["confidence"] == pytest.approx(2 / 3, abs=1e-3)
    assert cluster["matches_incident_label"] is True
    assert set(cluster["members"]) == {"old_a", "old_b", "old_c"}
    assert any(cmd[0] == "VSIM" for cmd in client.commands)


def test_cluster_incident_rejects_nonpositive_k(monkeypatch) -> None:
    client = _FakeRedis(vsim=["old_a", "0.95"])
    _store_labeled(client, "ws_dev", "old_a", "goal_mismatch")
    _install(monkeypatch, client)
    monkeypatch.setenv("VOYAGE_API_KEY", "x")
    monkeypatch.setattr(memory, "_embed", lambda text: [1.0, 0.0])

    assert memory.cluster_incident(_query_bundle(), k=0) is None
