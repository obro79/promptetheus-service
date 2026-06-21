"""Run one SDK-wrapped smoke agent against Promptetheus.

This is for hackathon teammate testing:

1. Point PROMPTETHEUS_API_URL at the FastAPI gateway.
2. Set PROMPTETHEUS_API_KEY to a project key, not a Supabase DB password.
3. Run this with the Promptetheus SDK importable.

The script prints the trace id and a Supabase SQL query to verify persistence.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _load_sdk():
    sdk_path = os.environ.get("PROMPTETHEUS_SDK_PATH")
    if sdk_path:
        sys.path.insert(0, str(Path(sdk_path).expanduser().resolve()))

    import promptetheus as pt  # type: ignore

    if not hasattr(pt, "trace"):
        imported_from = getattr(pt, "__file__", "unknown")
        raise RuntimeError(
            "Imported promptetheus without SDK tracing support from "
            f"{imported_from}. Run this from the promptetheus-sdk checkout, "
            "or set PROMPTETHEUS_SDK_PATH to the SDK package path."
        )
    return pt


def main() -> int:
    pt = _load_sdk()

    api_url = _required_env("PROMPTETHEUS_API_URL").rstrip("/")
    api_key = _required_env("PROMPTETHEUS_API_KEY")
    trace_id = os.environ.get("PROMPTETHEUS_TRACE_ID") or (
        f"trace_hackathon_{uuid.uuid4().hex[:12]}"
    )
    agent_name = os.environ.get("PROMPTETHEUS_AGENT_NAME", "hackathon-sdk-agent")

    with pt.trace.start(
        agent=agent_name,
        user_goal="Hackathon smoke test: prove SDK events persist in Supabase",
        session_id=trace_id,
        endpoint=api_url,
        api_key=api_key,
        transport="http",
        environment=os.environ.get("PROMPTETHEUS_ENVIRONMENT", "hackathon-smoke"),
        metadata={"source": "scripts/hackathon_sdk_smoke_agent.py"},
        tags=["hackathon", "sdk", "supabase-smoke"],
    ) as session:
        session.event(
            "user_message",
            {"content": "Run the Promptetheus hackathon persistence smoke test."},
        )
        session.browser_action("open", "https://example.com/hackathon-smoke")
        session.event(
            "tool_call",
            {"name": "fake_lookup", "arguments": {"query": "persist this event"}},
        )
        session.event(
            "tool_result",
            {"name": "fake_lookup", "status": "ok", "content": "events accepted"},
        )
        session.agent_message("Smoke test completed and events were emitted.")
        session.goal_check(True, mismatches=[])
        session.end("success")

    print(f"Sent Promptetheus SDK smoke trace: {trace_id}")
    print()
    print("Verify in Supabase SQL editor:")
    print(
        "select session_id, seq, type, payload "
        "from trace_event "
        f"where session_id = '{trace_id}' "
        "order by seq;"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
