"""Small deterministic agent run executed by the live E2E test subprocess."""

from __future__ import annotations

import os
from pathlib import Path

import promptetheus as pt


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required for SDK live-agent run")
    return value


def main() -> int:
    sdk_path = Path(_required_env("PROMPTETHEUS_SDK_PATH")).resolve()
    imported_from = Path(pt.__file__).resolve()
    if sdk_path not in imported_from.parents:
        raise RuntimeError(
            f"expected SDK import from {sdk_path}, got {imported_from}"
        )

    api_url = _required_env("PROMPTETHEUS_E2E_API_URL")
    api_key = _required_env("PROMPTETHEUS_E2E_API_KEY")
    trace_id = _required_env("PROMPTETHEUS_E2E_TRACE_ID")

    secret_token = os.environ.get("PROMPTETHEUS_E2E_SECRET_TOKEN", "sk-live-e2e-demo-secret-123456")
    secret_password = os.environ.get("PROMPTETHEUS_E2E_SECRET_PASSWORD", "live-e2e-password")

    with pt.trace.start(
        agent="live-e2e-agent",
        user_goal="Book a meeting room for Tuesday",
        session_id=trace_id,
        endpoint=api_url,
        api_key=api_key,
        transport="http",
        environment="live-e2e",
        metadata={"suite": "live_agent_supabase_mcp"},
        tags=["live-e2e", "sdk", "supabase", "mcp"],
    ) as session:
        session.event(
            "user_message",
            {
                "content": "Book the small room for Tuesday at 2pm",
                "authorization": f"Bearer {secret_token}",
            },
        )
        session.event(
            "browser_action",
            {
                "action": "click",
                "target": "#wednesday",
                "password": secret_password,
            },
        )
        session.dom_snapshot(
            "https://acmemeet.example.test/rooms",
            "Tuesday Wednesday Room unavailable",
            selected_values={"day": "Wednesday"},
            warnings=["Room unavailable"],
        )
        session.browser_action("submit", "#confirm")
        session.agent_message("Done! Successfully booked.")
        session.goal_check(False, mismatches=["booked Wednesday, not Tuesday"])
        session.end("success")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
