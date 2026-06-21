"""Redis-backed fix memory + live heal timeline.

Three capabilities, all of which **degrade to safe no-ops without `REDIS_URL`** so
the loop is unaffected when Redis is absent (tests, local dev):

1. **Fix memory** — verified incident->fix pairs are stored with an embedding of
   their root cause. Before each fix-agent call the loop queries for similar past
   fixes and passes them as warm-start context, so the agent reuses known fixes and
   visibly "learns over time" (the data-flywheel moat read-only tools can't have).
   Embeddings use Voyage (`voyage-3`) when `VOYAGE_API_KEY` is set; otherwise a
   lexical token-overlap score keeps the feature working without an embedder.

2. **Vector similarity ("redis iris")** — when Redis 8 Vector Sets are available,
   fixes are indexed with `VADD` and retrieved with `VSIM` (HNSW KNN over cosine
   similarity) so similar incidents/sessions are clustered without an O(n) Python
   scan. The plain per-id scan + lexical scoring remains the fallback when Vector
   Sets, embeddings, or Redis itself are unavailable, so behavior never regresses.

3. **Timeline** — each loop attempt is `XADD`ed to a Redis Stream `heal:{id}` so
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

#: Default number of similar fixes to surface as advanced fix-agent context.
_DEFAULT_SIMILAR_LIMIT = 3

#: Default neighbourhood size (k) for KNN-vote incident clustering.
_DEFAULT_CLUSTER_K = 5

_client: Any = None
_client_resolved = False


def _redis() -> Any:
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
        import redis

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
        import voyageai

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


def _vector_key(workspace: str) -> str:
    return f"ptvec:{workspace}"


def _vadd(client: Any, workspace: str, element: str, vec: list[float], attrs: dict[str, Any]) -> None:
    """Index one embedding into the workspace Vector Set. Never raises."""

    try:
        args: list[Any] = ["VADD", _vector_key(workspace), "VALUES", str(len(vec))]
        args.extend(str(x) for x in vec)
        args.append(element)
        args.extend(["SETATTR", json.dumps(attrs, default=str)])
        client.execute_command(*args)
    except Exception:
        return


def _vsim(client: Any, workspace: str, vec: list[float], count: int) -> list[tuple[str, float]]:
    """KNN over the workspace Vector Set: [(element, similarity)]. Never raises."""

    try:
        args: list[Any] = ["VSIM", _vector_key(workspace), "VALUES", str(len(vec))]
        args.extend(str(x) for x in vec)
        args.extend(["WITHSCORES", "COUNT", str(count)])
        raw = client.execute_command(*args)
    except Exception:
        return []
    return _parse_vsim(raw)


def _parse_vsim(raw: Any) -> list[tuple[str, float]]:
    """Parse a VSIM ...WITHSCORES reply into [(element, score)]. Never raises."""

    out: list[tuple[str, float]] = []
    try:
        if isinstance(raw, dict):
            for element, score in raw.items():
                out.append((str(element), float(score)))
            return out
        if isinstance(raw, (list, tuple)):
            items = list(raw)
            for i in range(0, len(items) - 1, 2):
                out.append((str(items[i]), float(items[i + 1])))
    except Exception:
        return []
    return out


def _load_row(client: Any, workspace: str, fix_id: str) -> dict[str, Any] | None:
    raw = client.get(f"ptfix:{workspace}:{fix_id}")
    if not raw:
        return None
    try:
        row = json.loads(raw)
    except Exception:
        return None
    return row if isinstance(row, dict) else None


def _as_match(row: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "from_incident_id": row.get("incident_id"),
        "label": row.get("label"),
        "diff": row.get("diff"),
        "plan": row.get("plan"),
        "score": round(score, 3),
    }


def _neighbors(bundle: dict[str, Any], limit: int) -> list[tuple[float, dict[str, Any]]]:
    """Nearest stored fixes to bundle's incident as `(score, row)`. Never raises.

    Prefers a Redis Vector Set KNN query (`VSIM`) when an embedding is available;
    falls back to an O(n) scan with cosine (embeddings) or lexical (no embedder)
    scoring. Excludes the bundle's own incident and entries below the threshold,
    and returns at most `limit` rows sorted by descending similarity.
    """

    client = _redis()
    if client is None:
        return []
    try:
        incident = bundle.get("incident") or {}
        workspace = incident.get("workspace_id") or "ws"
        current_id = incident.get("id")
        sig = _signature(bundle)
        query_vec = _embed(sig)

        scored: list[tuple[float, dict[str, Any]]] = []

        # Vector path: KNN over the workspace Vector Set (Redis 8 "iris").
        if query_vec:
            for element, score in _vsim(client, workspace, query_vec, limit + 5):
                if element == current_id:
                    continue
                row = _load_row(client, workspace, element)
                if row is None:
                    continue
                if score >= _SIMILARITY_THRESHOLD:
                    scored.append((score, row))
            if scored:
                scored.sort(key=lambda item: item[0], reverse=True)
                return scored[:limit]

        # Fallback: scan every stored fix and score it directly.
        ids = client.smembers(f"ptfix:ids:{workspace}")
        if not ids:
            return []
        for fix_id in ids:
            row = _load_row(client, workspace, fix_id)
            if row is None or row.get("incident_id") == current_id:
                continue
            if query_vec and row.get("embedding"):
                score = _cosine(query_vec, row["embedding"])
                threshold = _SIMILARITY_THRESHOLD
            else:
                score = _lexical(sig, row.get("signature", ""))
                threshold = _LEXICAL_THRESHOLD
            if score >= threshold:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:limit]
    except Exception:
        return []


def _ranked_similar(bundle: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """Rank verified past fixes by similarity to bundle's incident. Never raises."""

    return [_as_match(row, score) for score, row in _neighbors(bundle, limit)]


def find_similar_fix(bundle: dict[str, Any]) -> dict[str, Any] | None:
    """Best verified past fix for a similar incident, or None. Never raises."""

    matches = _ranked_similar(bundle, 1)
    return matches[0] if matches else None


def find_similar_fixes(
    bundle: dict[str, Any], limit: int = _DEFAULT_SIMILAR_LIMIT
) -> list[dict[str, Any]]:
    """Top-`limit` verified past fixes for similar incidents. Never raises.

    Used to assemble advanced fix-agent context (e.g. the Devin runner) so the
    agent can see several prior remediations of the same class of failure rather
    than a single warm-start.
    """

    if limit < 1:
        return []
    return _ranked_similar(bundle, limit)


def cluster_incident(
    bundle: dict[str, Any], k: int = _DEFAULT_CLUSTER_K
) -> dict[str, Any] | None:
    """Assign the incident to a cluster via KNN majority vote. Never raises.

    Runs a `k`-nearest-neighbour query over the workspace Vector Set (`VSIM`, with
    the same cosine/lexical fallbacks as retrieval) and votes on the neighbours'
    failure labels. The winning label is the incident's cluster; the vote share is
    a confidence. Returns ``None`` when memory is unavailable or no neighbour
    clears the similarity threshold, so the loop degrades to a safe no-op.

    Returned shape::

        {
            "label": str,            # cluster (majority neighbour label)
            "size": int,             # neighbours that formed the cluster
            "members": list[str],    # neighbour incident ids
            "confidence": float,     # winning vote share in [0, 1]
            "mean_score": float,     # mean neighbour similarity
            "matches_incident_label": bool,
        }
    """

    if k < 1:
        return None
    neighbors = _neighbors(bundle, k)
    if not neighbors:
        return None

    votes: dict[str, int] = {}
    members: list[str] = []
    score_sum = 0.0
    for score, row in neighbors:
        label = str(row.get("label") or "unlabeled")
        votes[label] = votes.get(label, 0) + 1
        member_id = row.get("incident_id")
        if member_id is not None:
            members.append(str(member_id))
        score_sum += score

    total = len(neighbors)
    cluster_label, vote_count = max(votes.items(), key=lambda item: item[1])
    incident = bundle.get("incident") or {}
    return {
        "label": cluster_label,
        "size": total,
        "members": members,
        "confidence": round(vote_count / total, 3),
        "mean_score": round(score_sum / total, 3),
        "matches_incident_label": cluster_label == (incident.get("label") or None),
    }


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
        embedding = _embed(sig)
        row = {
            "incident_id": incident_id,
            "label": incident.get("label"),
            "signature": sig,
            "root_cause": bundle.get("root_cause"),
            "diff": getattr(fix_result, "diff", None),
            "plan": list(getattr(fix_result, "plan", []) or []),
            "embedding": embedding,
            "stored_at": time.time(),
        }
        client.set(f"ptfix:{workspace}:{incident_id}", json.dumps(row))
        client.sadd(f"ptfix:ids:{workspace}", incident_id)
        # Index into the Vector Set for KNN retrieval when an embedder is present.
        if embedding:
            _vadd(
                client,
                workspace,
                incident_id,
                embedding,
                {"label": incident.get("label"), "incident_id": incident_id},
            )
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


__all__ = [
    "cluster_incident",
    "find_similar_fix",
    "find_similar_fixes",
    "remember_fix",
    "timeline_publish",
    "timeline_read",
]
