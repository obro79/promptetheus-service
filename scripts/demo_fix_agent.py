#!/usr/bin/env python3
"""Standalone end-to-end demo of the fix-agent vector memory + Devin runner.

Runs the PR-22 chain **without the FastAPI gateway**, calling the modules directly:

    remember_fix  -> VADD (index a verified past fix into a Redis 8 Vector Set)
    find_similar_fixes -> VSIM (HNSW KNN retrieval of the nearest past fix)
    DevinRunner.run -> creates a real Devin session seeded with that fix as
                       "advanced context", polls for a structured {diagnosis,
                       plan, diff}, and enforces the path allow-list.

Environment variables
---------------------
REDIS_URL                   Redis 8 endpoint. Without it the memory layer is a
                            no-op (the runner still works, just no similar-fix
                            context). Example (your Terraform box):
                              redis://default:Billions%2Bfocus%4026@<ip>:6379/0
DEVIN_API_KEY               Required to actually create a Devin session. Without
                            it the runner cleanly falls back to the deterministic
                            runner (still a valid, allow-list-checked diff).
PROMPTETHEUS_DEVIN_ORG_ID   Set for enterprise Devin (v3 org-scoped API).
PROMPTETHEUS_DEVIN_MAX_ACU  Optional ACU cap for the session (e.g. 5).
VOYAGE_API_KEY              Real voyage-3 embeddings -> exercises VADD/VSIM with
                            the calibrated 0.78 cosine gate.
PROMPTETHEUS_DEMO_FAKE_EMBED=1
                            No Voyage key? Set this and the demo installs a
                            deterministic local embedder so the real VADD/VSIM
                            path still runs against Redis 8. (Demo-only; never
                            used by the service.)

Usage
-----
    python -m pip install -e "packages/promptetheus[server]"
    REDIS_URL=... DEVIN_API_KEY=... PROMPTETHEUS_DEVIN_ORG_ID=... \
        python scripts/demo_fix_agent.py
"""

from __future__ import annotations

import hashlib
import os
import sys
from types import SimpleNamespace
from typing import Any

from promptetheus.server.fix_agent import memory
from promptetheus.server.fix_agent.runners.devin import DevinRunner

WORKSPACE = "demo-fix-agent"


def _fake_embed(text: str) -> list[float]:
    """Deterministic hashed bag-of-words embedding (demo only).

    Similar text -> similar vectors, so VADD/VSIM behave like a real embedder
    without needing a Voyage key. Not used anywhere in the service.
    """

    dim = 256
    vec = [0.0] * dim
    for token in text.lower().split():
        if len(token) <= 2:
            continue
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    return vec


def _banner(title: str) -> None:
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


def _incident(incident_id: str, label: str) -> dict[str, Any]:
    return {
        "id": incident_id,
        "label": label,
        "severity": "high",
        "confidence": 0.91,
        "workspace_id": WORKSPACE,
    }


def _bundle(incident: dict[str, Any], root_cause: str, user_goal: str) -> dict[str, Any]:
    return {
        "incident": incident,
        "root_cause": root_cause,
        "user_goal": user_goal,
        "source": "demo",
        "allowed_paths": ["agents/"],
        "events": [
            {"seq": 1, "type": "tool_call", "name": "calendar.lookup"},
            {"seq": 2, "type": "tool_call", "name": "email.send"},
            {"seq": 3, "type": "error", "message": "no tool named email.send registered"},
        ],
    }


def main() -> int:
    redis_on = bool(os.environ.get("REDIS_URL"))
    voyage_on = bool(os.environ.get("VOYAGE_API_KEY"))
    fake_embed = os.environ.get("PROMPTETHEUS_DEMO_FAKE_EMBED") == "1"

    if fake_embed and not voyage_on:
        memory._embed = _fake_embed  # type: ignore[assignment]

    _banner("Config")
    client = memory._redis()
    print(f"REDIS_URL set          : {redis_on}")
    print(f"Redis reachable        : {client is not None}")
    if client is not None:
        try:
            info = client.info("server")
            print(f"Redis version          : {info.get('redis_version')}")
        except Exception as exc:  # noqa: BLE001
            print(f"Redis INFO failed      : {exc}")
    embed_mode = "voyage-3" if voyage_on else ("fake-local" if fake_embed else "none (lexical fallback)")
    print(f"Embedder               : {embed_mode}")
    print(f"DEVIN_API_KEY set      : {bool(os.environ.get('DEVIN_API_KEY'))}")
    print(f"Devin org (enterprise) : {os.environ.get('PROMPTETHEUS_DEVIN_ORG_ID') or '(v1 public)'}")

    # Clean prior demo state so re-runs are deterministic.
    if client is not None:
        try:
            keys = client.keys(f"ptfix:*{WORKSPACE}*") + client.keys(f"ptvec:{WORKSPACE}")
            ids = client.smembers(f"ptfix:ids:{WORKSPACE}")
            for fid in ids:
                keys.append(f"ptfix:{WORKSPACE}:{fid}")
            if keys:
                client.delete(*set(keys))
        except Exception:
            pass

    # 1) Seed a verified PAST fix: the agent crashed because email.send wasn't registered.
    _banner("Step 1 - remember_fix (VADD): index a verified past fix")
    past = _incident("inc-email-001", "missing_capability")
    past_bundle = _bundle(
        past,
        root_cause="agent invoked email.send but no such tool was registered (missing capability)",
        user_goal="schedule a meeting and email the attendees",
    )
    past_fix = SimpleNamespace(
        diff=(
            "--- /dev/null\n"
            "+++ b/agents/tools/email_send.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+def email_send(to, subject, body):\n"
            "+    \"\"\"Register an email.send capability.\"\"\"\n"
            "+    return _smtp_send(to, subject, body)\n"
        ),
        plan=["Add an email_send tool", "Register it in the tool registry"],
    )
    memory.remember_fix(past, past_bundle, past_fix)
    if client is not None:
        try:
            vcard = client.execute_command("VCARD", f"ptvec:{WORKSPACE}")
            print(f"stored fix '{past['id']}' | Vector Set VCARD = {vcard}")
        except Exception as exc:  # noqa: BLE001
            print(f"stored fix '{past['id']}' | VCARD unavailable ({exc}) - lexical fallback path")
    else:
        print("Redis off - remember_fix was a no-op (expected without REDIS_URL)")

    # 2) A NEW, similar incident arrives. Retrieve the nearest past fix via VSIM.
    _banner("Step 2 - find_similar_fixes (VSIM): retrieve nearest past fix")
    new = _incident("inc-email-002", "missing_capability")
    new_bundle = _bundle(
        new,
        root_cause="agent tried to call email.send tool but it was not registered (missing capability)",
        user_goal="book a calendar slot and notify guests over email",
    )
    similar = memory.find_similar_fixes(new_bundle)
    print(f"matches returned       : {len(similar)}")
    for s in similar:
        print(f"  - from {s.get('from_incident_id')} | label={s.get('label')} | score={s.get('score')}")
    if not similar and redis_on:
        print("  (no match above threshold - with a crude embedder try PROMPTETHEUS_DEMO_FAKE_EMBED=1,")
        print("   or set VOYAGE_API_KEY for real voyage-3 embeddings)")

    # 3) Hand the new incident to the Devin runner. It injects `similar` as advanced
    #    context, creates a real session, and returns a validated structured fix.
    _banner("Step 3 - DevinRunner.run: create a real Devin session with that context")
    if not os.environ.get("DEVIN_API_KEY"):
        print("DEVIN_API_KEY not set - the runner will fall back to the deterministic runner.")
    runner = DevinRunner(allowed_paths=["agents/"])
    result = runner.run(new_bundle)

    _banner("Result")
    print(f"runner                 : {result.runner}")
    print(f"fallback               : {result.fallback}")
    print(f"similar_fix_count      : {result.metadata.get('similar_fix_count')}")
    print(f"similar_fix_ids        : {result.metadata.get('similar_fix_ids')}")
    print(f"session_url            : {result.metadata.get('session_url')}")
    print(f"diagnosis              : {result.summary}")
    print(f"changed_files          : {result.changed_files}")
    print("diff (first 600 chars):")
    print((result.diff or "")[:600])

    if result.fallback and os.environ.get("DEVIN_API_KEY"):
        print(
            "\nNote: runner fell back. If DEVIN_API_KEY is set this usually means the\n"
            "session errored, timed out, or returned a diff outside agents/. Check the\n"
            "session_url above (None means session creation itself failed)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
