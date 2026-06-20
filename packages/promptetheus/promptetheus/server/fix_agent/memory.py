"""Redis-backed fix memory + live heal timeline.

Two capabilities, both **degrade to safe no-ops without `REDIS_URL`** so the loop
is unaffected when Redis is absent (tests, local dev):

1. **Fix memory** — verified incident->fix pairs are stored with an embedding of
   their root cause. Before each Claude call the loop queries for a similar past
   fix and passes it as a warm-start, so the agent reuses known fixes and visibly
   "learns over time" (the data-flywheel moat read-only tools can't have).
   Embeddings use Voyage (`voyage-3`) when `VOYAGE_API_KEY` is set; otherwise a
   lexical token-overlap score keeps the feature working without an embedder.

2. **Timeline** — each loop attempt is `XADD`ed to a Redis Stream `heal:{id}` so
   the console can render the heal loop live.

Every function catches its own errors and returns a safe default — memory failures
must never break remediation.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any

_SIMILARITY_THRESHOLD = 0.78
_LEXICAL_THRESHOLD = 0.5

_client: Any = None
_client_resolved = False


def _redis():
    """Return a cached redis client, or None if unavailable. Never raises."""

    global _client, _client_resolved
    if _client_resolved:
        return _client
    _client_resolved = True
    url = os.environ.get("REDIS_URL")
    if not url:
        _client = None
        return None
    try:
        import redis  # type: ignore

        client = redis.from_url(url, decode_responses=True)
        client.ping()
        _client = client
    except Exception:
        _client = None
    return _client


def _embed(text: str) -> list[float] | None:
    """Voyage embedding of text, or None when no embedder is configured."""

    if not os.environ.get("VOYAGE_API_KEY"):
        return None
    try:
        import voyageai  # type: ignore

        result = voyageai.Client().embed([text], model="voyage-3", input_type="document")
        return list(result.embeddings[0])
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _lexical(a: str, b: str) -> float:
    ta = {t for t in a.lower().split() if len(t) > 2}
    tb = {t for t in b.lower().split() if len(t) > 2}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _signature(bundle: dict[str, Any]) -> str:
    incident = bundle.get("incident") or {}
    return f"{incident.get('label') or ''} {bundle.get('root_cause') or ''}".strip()


def find_similar_fix(bundle: dict[str, Any]) -> dict[str, Any] | None:
    """Best verified past fix for a similar incident, or None. Never raises."""

    client = _redis()
    if client is None:
        return None
    try:
        incident = bundle.get("incident") or {}
        workspace = incident.get("workspace_id") or "ws"
        ids = client.smembers(f"ptfix:ids:{workspace}")
        if not ids:
            return None
        sig = _signature(bundle)
        query_vec = _embed(sig)
        best: dict[str, Any] | None = None
        best_score = 0.0
        for fix_id in ids:
            raw = client.get(f"ptfix:{workspace}:{fix_id}")
            if not raw:
                continue
            row = json.loads(raw)
            if row.get("incident_id") == incident.get("id"):
                continue  # don't warm-start from the same incident
            if query_vec and row.get("embedding"):
                score = _cosine(query_vec, row["embedding"])
                threshold = _SIMILARITY_THRESHOLD
            else:
                score = _lexical(sig, row.get("signature", ""))
                threshold = _LEXICAL_THRESHOLD
            if score >= threshold and score > best_score:
                best, best_score = row, score
        if best is None:
            return None
        return {
            "from_incident_id": best.get("incident_id"),
            "label": best.get("label"),
            "diff": best.get("diff"),
            "plan": best.get("plan"),
            "score": round(best_score, 3),
        }
    except Exception:
        return None


def remember_fix(
    incident: dict[str, Any], bundle: dict[str, Any], fix_result: Any
) -> None:
    """Store a verified incident->fix pair for future warm-starts. Never raises."""

    client = _redis()
    if client is None:
        return
    try:
        workspace = incident.get("workspace_id") or "ws"
        incident_id = str(incident.get("id") or "incident")
        sig = _signature(bundle)
        row = {
            "incident_id": incident_id,
            "label": incident.get("label"),
            "signature": sig,
            "root_cause": bundle.get("root_cause"),
            "diff": getattr(fix_result, "diff", None),
            "plan": list(getattr(fix_result, "plan", []) or []),
            "embedding": _embed(sig),
            "stored_at": time.time(),
        }
        client.set(f"ptfix:{workspace}:{incident_id}", json.dumps(row))
        client.sadd(f"ptfix:ids:{workspace}", incident_id)
    except Exception:
        return


def timeline_publish(incident_id: str, event: dict[str, Any]) -> None:
    """XADD one heal-loop event to stream heal:{incident_id}. Never raises."""

    client = _redis()
    if client is None:
        return
    try:
        client.xadd(
            f"heal:{incident_id}",
            {"event": json.dumps(event, default=str)},
            maxlen=200,
            approximate=True,
        )
    except Exception:
        return


def timeline_read(incident_id: str) -> list[dict[str, Any]]:
    """Read the heal timeline for an incident (for the console). Never raises."""

    client = _redis()
    if client is None:
        return []
    try:
        entries = client.xrange(f"heal:{incident_id}")
        out: list[dict[str, Any]] = []
        for _id, fields in entries:
            raw = fields.get("event")
            if raw:
                out.append(json.loads(raw))
        return out
    except Exception:
        return []


__all__ = ["find_similar_fix", "remember_fix", "timeline_publish", "timeline_read"]
