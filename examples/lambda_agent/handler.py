"""A tiny AWS-Lambda-style agent that feeds the Promptetheus heal loop.

This proves the **agnostic source seam**: the same remediation pipeline that
heals Browserbase incidents also heals incidents from a Lambda-hosted agent.
The handler runs a toy "booking" agent that fails its goal, then POSTs the trace
to the existing FastAPI ingestion endpoints tagged ``source="lambda"`` so the
incident flows through `POST /api/incidents/{id}/heal` exactly like any other.

It depends only on the stdlib (so it drops into a Lambda zip with no layers) and
talks to the same locked endpoints the SDK uses:

    POST /api/traces                      (api key)   -> create the session
    POST /api/traces/{id}/events          (api key)   -> the failure timeline
    POST /api/traces/{id}/analyze         (console)   -> detectors form the incident

Run locally against `promptetheus dev`:

    python examples/lambda_agent/handler.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

BASE_URL = os.environ.get("PROMPTETHEUS_BASE_URL", "http://127.0.0.1:4318").rstrip("/")
API_KEY = os.environ.get("PROMPTETHEUS_API_KEY", "pt_dev_key")
CONSOLE_TOKEN = os.environ.get("PROMPTETHEUS_CONSOLE_TOKEN", "pt_console_token")
SOURCE = "lambda"

GOAL = "Book a 30 minute AcmeMeet with Dana on Tuesday at 2pm"


def _post(path: str, body: dict[str, Any], token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:  # surface the server's reason, don't swallow it
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"POST {path} failed: {exc.code} {detail}") from exc


def _event(session_id: str, seq: int, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    ts = datetime(2026, 6, 20, 9, 0, seq, tzinfo=timezone.utc).isoformat()
    return {
        "type": event_type,
        "session_id": session_id,
        "timestamp": ts,
        "seq": seq,
        "idempotency_key": f"{session_id}:{seq}",
        "payload": payload,
    }


def _timeline(session_id: str) -> list[dict[str, Any]]:
    """A goal-mismatch failure: the agent confidently books the WRONG slot."""

    return [
        _event(session_id, 0, "user_message", {"content": GOAL}),
        _event(
            session_id,
            1,
            "tool_call",
            {"tool_name": "acmemeet_book", "arguments": {"goal": GOAL}, "call_id": f"{session_id}:t"},
        ),
        _event(
            session_id,
            2,
            "browser_action",
            {"action": "click", "target": "#slot-tuesday-2pm", "url": "https://acmemeet.local/book"},
        ),
        _event(
            session_id,
            3,
            "dom_snapshot",
            {
                "url": "https://acmemeet.local/book/review",
                "visible_text": "Selected Wednesday 4:00pm. Tuesday is full.",
                "selected_values": {"slot": "Wednesday 4:00pm"},
                "warnings": ["Requested time unavailable"],
            },
        ),
        _event(session_id, 4, "browser_action", {"action": "submit", "target": "#confirm"}),
        _event(
            session_id,
            5,
            "agent_message",
            {"content": "Done! I booked your 30 minute AcmeMeet with Dana."},
        ),
        _event(
            session_id,
            6,
            "goal_check",
            {"passed": False, "mismatches": ["Booked Wednesday 4:00pm, not Tuesday 2:00pm"]},
        ),
        _event(session_id, 7, "session_end", {"status": "completed"}),
    ]


def run(session_id: str | None = None) -> dict[str, Any]:
    """Ingest one failing Lambda-agent run and form its incident. Returns a summary."""

    session_id = session_id or f"lambda_acmemeet_{int(datetime.now(timezone.utc).timestamp())}"

    _post("/api/traces", {"id": session_id, "user_goal": GOAL, "source": SOURCE}, API_KEY)
    accepted = _post(
        f"/api/traces/{session_id}/events", {"events": _timeline(session_id)}, API_KEY
    )
    analyzed = _post(f"/api/traces/{session_id}/analyze", {}, CONSOLE_TOKEN)

    incidents = analyzed.get("incidents") or []
    return {
        "session_id": session_id,
        "source": SOURCE,
        "events_accepted": accepted.get("accepted"),
        "incident_ids": [inc.get("id") for inc in incidents],
    }


def handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    """AWS Lambda entry point."""

    result = run((event or {}).get("session_id"))
    return {"statusCode": 200, "body": json.dumps(result)}


if __name__ == "__main__":
    summary = run()
    print(json.dumps(summary, indent=2))
    if not summary["incident_ids"]:
        print("\nNote: no incident formed — check the detector or that the server is seeded.")
