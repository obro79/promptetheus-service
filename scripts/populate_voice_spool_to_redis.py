#!/usr/bin/env python3
"""Populate the fix-agent Redis vector memory from voice-agent spool files.

Reads the SDK trace spool (`.promptetheus/spool/*.jsonl`) for the voice agent,
derives one incident->fix memory entry per session, and stores it through the
real service path:

    remember_fix(incident, bundle, fix_result)
        -> Voyage `voyage-3` embedding of the signature
        -> VADD into the Redis 8 Vector Set  (ptvec:{workspace})
        -> row at ptfix:{workspace}:{incident_id}

Failure sessions (goal_check passed=false) become incidents whose "fix" is the
scope-guard correction; passing sessions are stored as verified good runs. A
future similar incident then warm-starts via VSIM (KNN) retrieval.

Requires REDIS_URL and VOYAGE_API_KEY in the environment (load your .env first).

Usage:
    set -a; . ./.env; set +a
    .venv/bin/python scripts/populate_voice_spool_to_redis.py \
        --spool /Users/tarive/demo_agents/demo-agents/agents/voice_agents/.promptetheus/spool \
        --workspace ws_dev
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from types import SimpleNamespace
from typing import Any

from promptetheus.server.fix_agent import memory

DEFAULT_SPOOL = (
    "/Users/tarive/demo_agents/demo-agents/agents/voice_agents/.promptetheus/spool"
)


def _load_session(path: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in open(path).read().splitlines() if line.strip()]


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract goal, refund tool-calls, and the goal_check verdict from a session."""

    session_id = rows[0]["session_id"]
    goal = ""
    refunds: list[dict[str, Any]] = []
    mismatches: list[str] = []
    passed = True
    for r in rows:
        t, p = r["type"], r.get("payload", {})
        if t == "state_change" and p.get("name") == "session_started":
            goal = (p.get("after") or {}).get("user_goal", "")
        elif t == "tool_call" and p.get("tool_name") == "issue_refund":
            refunds.append(p.get("arguments", {}))
        elif t == "goal_check":
            passed = bool(p.get("passed", True))
            mismatches = list(p.get("mismatches") or [])
    return {
        "session_id": session_id,
        "goal": goal,
        "refunds": refunds,
        "passed": passed,
        "mismatches": mismatches,
    }


def _to_memory_entry(s: dict[str, Any], workspace: str) -> tuple[dict, dict, Any]:
    """Build (incident, bundle, fix_result) for remember_fix from a session summary."""

    refunded = ", ".join(
        r.get("item", "?") for r in s["refunds"]
    ) or "nothing"
    if not s["passed"]:
        label = "out_of_scope_action"
        root_cause = (
            "Voice refund agent " + "; ".join(s["mismatches"])
            + f" (approved: {refunded}). It should refund only in-scope dental "
            "items and decline out-of-scope requests."
        )
        plan = [
            "Guard issue_refund: only approve items in the dental service catalog.",
            "Decline out-of-scope requests (e.g. car-fuel discounts) explicitly.",
            "Re-run the goal_check before session_end and block on mismatches.",
        ]
        diff = (
            "--- a/voice_agents/refund.py\n+++ b/voice_agents/refund.py\n"
            "@@ def issue_refund(item, **kw):\n"
            "+    if item not in DENTAL_CATALOG:\n"
            "+        return decline(item, reason='out_of_scope')\n"
        )
    else:
        label = "scope_respected"
        root_cause = (
            f"Voice refund agent correctly refunded {refunded} and declined the "
            "out-of-scope car-fuel discount. Verified good run."
        )
        plan = ["No fix needed - behavior matches the refund policy."]
        diff = None

    incident = {
        "workspace_id": workspace,
        "id": f"voice_{s['session_id']}",
        "label": label,
    }
    bundle = {"incident": incident, "root_cause": root_cause}
    fix_result = SimpleNamespace(diff=diff, plan=plan)
    return incident, bundle, fix_result


# Must equal _signature({"incident": {...no label...}, "root_cause": _PROBE_SIG}),
# which is just the stripped root_cause, so the batched embedding is cache-hit.
_PROBE_SIG = "the voice agent approved an out-of-scope discount it should have declined"


def _batch_embed(texts: list[str], *, retries: int = 4, wait: float = 22.0) -> list[list[float]]:
    """Embed all texts in ONE Voyage call, retrying on the 3 RPM free-tier limit."""

    import time

    import voyageai

    client = voyageai.Client()
    for attempt in range(retries):
        try:
            res = client.embed(texts, model="voyage-3", input_type="document")
            return [list(v) for v in res.embeddings]
        except Exception as exc:  # RateLimitError etc.
            if "RateLimit" in type(exc).__name__ and attempt < retries - 1:
                print(f"  rate-limited; waiting {wait:.0f}s (free tier 3 RPM)...")
                time.sleep(wait)
                continue
            raise


def _reset_workspace(client: Any, workspace: str) -> None:
    client.delete(_vk := memory._vector_key(workspace))
    for fix_id in client.smembers(f"ptfix:ids:{workspace}") or []:
        client.delete(f"ptfix:{workspace}:{fix_id}")
    client.delete(f"ptfix:ids:{workspace}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spool", default=DEFAULT_SPOOL, help="Spool directory")
    parser.add_argument("--workspace", default="ws_dev", help="Workspace id key")
    parser.add_argument("--no-reset", action="store_true", help="Keep existing entries")
    args = parser.parse_args(argv)

    client = memory._redis()
    if client is None:
        print("ERROR: no Redis connection (set REDIS_URL). Aborting.")
        return 1
    if not os.environ.get("VOYAGE_API_KEY"):
        print("ERROR: VOYAGE_API_KEY not set; refusing to populate without embeddings.")
        return 1
    print(f"Redis: connected | embedder: voyage-3 | workspace: {args.workspace}")

    files = sorted(glob.glob(os.path.join(args.spool, "*.jsonl")))
    if not files:
        print(f"ERROR: no spool files in {args.spool}")
        return 1

    if not args.no_reset:
        _reset_workspace(client, args.workspace)
        print(f"  reset workspace keys for {args.workspace}")

    # Build all entries, then embed every signature (+ the probe) in ONE batch call.
    entries = []
    for path in files:
        s = _summarize(_load_session(path))
        incident, bundle, fix_result = _to_memory_entry(s, args.workspace)
        entries.append((s, incident, bundle, fix_result, memory._signature(bundle)))

    sigs = [e[4] for e in entries] + [_PROBE_SIG]
    print(f"  batch-embedding {len(sigs)} signatures in one Voyage call...")
    vectors = _batch_embed(sigs)
    cache = dict(zip(sigs, vectors))

    # Serve cached vectors so remember_fix / find_similar_fix make no extra API calls.
    memory._embed = lambda text: cache.get(text)  # type: ignore[assignment]

    stored = 0
    for s, incident, bundle, fix_result, sig in entries:
        memory.remember_fix(incident, bundle, fix_result)
        verdict = "PASS" if s["passed"] else "FAIL"
        print(f"  stored {incident['id']}  [{verdict}] {incident['label']}  ({len(cache[sig])}-dim)")
        stored += 1

    # Verify: vector-set cardinality + a live KNN retrieval.
    vcard = client.execute_command("VCARD", memory._vector_key(args.workspace))
    print(f"\nVector set {memory._vector_key(args.workspace)}: VCARD={vcard}")

    probe = {
        "incident": {"workspace_id": args.workspace, "id": "probe_new"},
        "root_cause": _PROBE_SIG,
    }
    match = memory.find_similar_fix(probe)
    print("\nKNN probe -> 'approved an out-of-scope discount it should have declined':")
    if match:
        print(f"  best match: {match.get('from_incident_id')}  "
              f"score={match.get('score'):.4f}  label={match.get('label')}")
        print(f"  plan: {match.get('plan')}")
    else:
        print("  no match above threshold")
    print(f"\nDone: {stored} sessions embedded into Redis vector memory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
