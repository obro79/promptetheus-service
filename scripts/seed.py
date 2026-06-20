"""Seed the State-0 stack with deterministic demo traces through the API.

The script drives the locked FastAPI contract end to end. By default it uses an
in-process TestClient, so a fresh checkout can seed demo incidents with:

    python scripts/seed.py

It can also target a running local or hosted API:

    python scripts/seed.py --api-url http://127.0.0.1:4318

For each session it:

1. POST /api/traces with a stable session id.
2. POST /api/traces/{id}/artifacts with screenshot and replay bytes.
3. POST /api/traces/{id}/events with a deterministic failure timeline.
4. POST /api/traces/{id}/analyze so detectors form incidents.
5. POST fix-agent and demo-profile regression runs for formed incidents.
"""

import argparse
import json as json_module
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

# Make the promptetheus package importable when this script is run directly
# as python scripts/seed.py from a fresh checkout (no editable install). The
# package lives under packages/promptetheus/; this mirrors the repo-root
# conftest.py bootstrap and is a no-op when the package is already importable.
_PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "packages" / "promptetheus"
if _PACKAGE_ROOT.is_dir():
    _package_root_str = str(_PACKAGE_ROOT)
    if _package_root_str not in sys.path:
        sys.path.insert(0, _package_root_str)


API_KEY = "pt_dev_key"
CONSOLE_TOKEN = "pt_console_token"

API_AUTH = {"Authorization": f"Bearer {API_KEY}"}
CONSOLE_AUTH = {"Authorization": f"Bearer {CONSOLE_TOKEN}"}


@dataclass(frozen=True)
class SeedScenario:
    agent: str
    surface: str
    goals: tuple[str, ...]
    tool_name: str
    action_target: str
    wrong_value: str
    selected_key: str
    warning: str
    success_claim: str
    mismatch_template: str


SCENARIOS: tuple[SeedScenario, ...] = (
    SeedScenario(
        agent="browser-agent",
        surface="browser",
        goals=(
            "Book a 30 minute AcmeMeet with Dana on Tuesday at 2pm",
            "Book a 30 minute AcmeMeet with Dana on Wednesday at 10am",
            "Book a 30 minute AcmeMeet with Dana on Thursday at 4pm",
            "Book a 30 minute AcmeMeet with Dana on Friday at 9am",
        ),
        tool_name="browser.click",
        action_target="#slot-monday-8am",
        wrong_value="Monday at 8am",
        selected_key="slot",
        warning="Selected slot conflicts with another meeting on the invitee calendar",
        success_claim="Successfully booked your AcmeMeet for Monday at 8am.",
        mismatch_template="Requested {goal} but selected Monday at 8am",
    ),
    SeedScenario(
        agent="support-agent",
        surface="chat",
        goals=(
            "Refund the duplicate Pro invoice for Maya and keep the account active",
            "Escalate the angry billing chat to a human before issuing credit",
            "Resolve the refund chat without closing the subscription",
        ),
        tool_name="support.lookup_thread",
        action_target="#issue-credit-and-close",
        wrong_value="credit issued and subscription closed",
        selected_key="resolution",
        warning="Refund policy says do not close active subscriptions for duplicate invoices",
        success_claim="Done, the billing issue is completed and the account is closed.",
        mismatch_template="Requested {goal} but the agent closed the subscription",
    ),
    SeedScenario(
        agent="coding-agent",
        surface="code",
        goals=(
            "Patch the checkout warning regression without changing billing flow",
            "Fix the UI warning replay while leaving auth middleware untouched",
            "Prepare a PR for the browser replay bug without editing payments",
        ),
        tool_name="repo.apply_patch",
        action_target="payments/checkout.py",
        wrong_value="payments/checkout.py rewritten",
        selected_key="changed_file",
        warning="Regression scope excludes payments and auth modules",
        success_claim="Completed the fix and updated the checkout payment path.",
        mismatch_template="Requested {goal} but changed an excluded payments file",
    ),
)


@dataclass
class ApiResponse:
    status_code: int
    _body: bytes

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        if not self._body:
            return {}
        return json_module.loads(self.text)


class HttpApiClient:
    """Small TestClient-shaped HTTP client for hosted/local API seeding."""

    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> ApiResponse:
        request_headers = dict(headers or {})
        if content is not None:
            data = content
        else:
            data = json_module.dumps(json or {}).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request_headers.setdefault("Accept", "application/json")
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=data,
            headers=request_headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return ApiResponse(int(response.status), response.read())
        except HTTPError as exc:
            return ApiResponse(exc.code, exc.read())


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ts(base: datetime, offset_seconds: int) -> str:
    return (base + timedelta(seconds=offset_seconds)).isoformat()


def _session_id(surface: str, index: int) -> str:
    return f"seed_{surface}_{index:02d}"


def _artifact_id(session_id: str, artifact_type: str) -> str:
    return f"artifact_{session_id}_{artifact_type}"


def _event(
    *,
    session_id: str,
    seq: int,
    event_type: str,
    payload: dict[str, Any],
    base: datetime,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": event_type,
        "session_id": session_id,
        "timestamp": _ts(base, seq),
        "seq": seq,
        "idempotency_key": f"{session_id}:{seq}",
        "payload": payload,
    }
    if metadata is not None:
        event["metadata"] = metadata
    return event


def _build_events(
    *,
    session_id: str,
    goal: str,
    scenario: SeedScenario,
    artifacts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a failure timeline that exercises current deterministic detectors."""

    base = datetime(2026, 6, 12, 9, 0, 0, tzinfo=timezone.utc)
    screenshot = artifacts.get("screenshot") or {}
    replay = artifacts.get("replay") or {}
    mismatch = scenario.mismatch_template.format(goal=goal)

    events = [
        _event(
            session_id=session_id,
            seq=0,
            event_type="user_message",
            payload={"content": goal},
            base=base,
            metadata={"surface": scenario.surface},
        ),
        _event(
            session_id=session_id,
            seq=1,
            event_type="tool_call",
            payload={
                "tool_name": scenario.tool_name,
                "arguments": {"goal": goal, "surface": scenario.surface},
                "call_id": f"{session_id}:tool",
            },
            base=base,
        ),
        _event(
            session_id=session_id,
            seq=2,
            event_type="browser_action",
            payload={
                "action": "click",
                "target": "#open-workflow",
                "url": f"https://demo.promptetheus.local/{scenario.surface}",
            },
            base=base,
        ),
        _event(
            session_id=session_id,
            seq=3,
            event_type="dom_snapshot",
            payload={
                "url": f"https://demo.promptetheus.local/{scenario.surface}",
                "visible_text": f"{scenario.surface} workspace ready",
                "selected_values": {},
                "warnings": [],
            },
            base=base,
        ),
        _event(
            session_id=session_id,
            seq=4,
            event_type="browser_action",
            payload={
                "action": "click",
                "target": scenario.action_target,
                "metadata": {"tool_name": scenario.tool_name},
            },
            base=base,
        ),
        _event(
            session_id=session_id,
            seq=5,
            event_type="dom_snapshot",
            payload={
                "url": f"https://demo.promptetheus.local/{scenario.surface}/review",
                "visible_text": (
                    f"Selected {scenario.wrong_value}. {scenario.warning}."
                ),
                "selected_values": {scenario.selected_key: scenario.wrong_value},
                "warnings": [scenario.warning],
            },
            base=base,
        ),
        _event(
            session_id=session_id,
            seq=6,
            event_type="browser_action",
            payload={"action": "submit", "target": "#confirm"},
            base=base,
        ),
    ]

    if screenshot:
        events.append(
            _event(
                session_id=session_id,
                seq=7,
                event_type="screenshot",
                payload={
                    "artifact_id": screenshot.get("artifact_id"),
                    "storage_path": screenshot.get("storage_path"),
                    "size_bytes": screenshot.get("size_bytes"),
                    "source_type": "seed",
                },
                base=base,
            )
        )

    events.extend(
        [
            _event(
                session_id=session_id,
                seq=8,
                event_type="agent_message",
                payload={"content": scenario.success_claim},
                base=base,
                metadata={"status": "success", "surface": scenario.surface},
            ),
            _event(
                session_id=session_id,
                seq=9,
                event_type="goal_check",
                payload={"passed": False, "mismatches": [mismatch]},
                base=base,
            ),
        ]
    )

    if replay:
        events.append(
            _event(
                session_id=session_id,
                seq=10,
                event_type="replay_artifact",
                payload={
                    "artifact_id": replay.get("artifact_id"),
                    "storage_path": replay.get("storage_path"),
                    "artifact_type": "screen_recording",
                    "event_time_map": {"2": 180, "5": 940, "6": 1410},
                },
                base=base,
            )
        )

    events.append(
        _event(
            session_id=session_id,
            seq=11,
            event_type="session_end",
            payload={"status": "completed"},
            base=base,
        )
    )
    return events


def _create_session(
    client: Any,
    *,
    session_id: str,
    goal: str,
    scenario: SeedScenario,
    api_auth: dict[str, str],
) -> str:
    response = client.post(
        "/api/traces",
        json={
            "id": session_id,
            "user_goal": goal,
            "agent": scenario.agent,
            "environment": "demo",
            "metadata": {"surface": scenario.surface, "seed": True},
            "tags": ["demo", scenario.surface, scenario.agent],
        },
        headers=api_auth,
    )
    if response.status_code != 201:
        raise RuntimeError(f"POST /api/traces failed: {response.status_code} {response.text}")
    return str(response.json()["trace"]["id"])


def _upload_artifacts(
    client: Any,
    *,
    session_id: str,
    scenario: SeedScenario,
    api_auth: dict[str, str],
) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    screenshot = client.post(
        f"/api/traces/{session_id}/artifacts",
        content=(
            b"\x89PNG\r\n\x1a\n"
            + f"promptetheus seed screenshot {scenario.surface}".encode("utf-8")
        ),
        headers={
            **api_auth,
            "Content-Type": "image/png",
            "X-Promptetheus-Filename": f"{scenario.surface}-step.png",
            "X-Promptetheus-Artifact-Type": "screenshot",
            "X-Promptetheus-Artifact-Id": _artifact_id(session_id, "screenshot"),
        },
    )
    if screenshot.status_code != 201:
        raise RuntimeError(
            f"POST /api/traces/{session_id}/artifacts failed: "
            f"{screenshot.status_code} {screenshot.text}"
        )
    artifacts["screenshot"] = screenshot.json()["artifact"]

    replay = client.post(
        f"/api/traces/{session_id}/artifacts",
        content=f"WEBM promptetheus seed replay {scenario.surface}".encode("utf-8"),
        headers={
            **api_auth,
            "Content-Type": "video/webm",
            "X-Promptetheus-Filename": f"{scenario.surface}-replay.webm",
            "X-Promptetheus-Artifact-Type": "replay",
            "X-Promptetheus-Artifact-Id": _artifact_id(session_id, "replay"),
        },
    )
    if replay.status_code != 201:
        raise RuntimeError(
            f"POST /api/traces/{session_id}/artifacts failed: "
            f"{replay.status_code} {replay.text}"
        )
    artifacts["replay"] = replay.json()["artifact"]
    return artifacts


def _post_events(
    client: Any,
    session_id: str,
    events: list[dict[str, Any]],
    api_auth: dict[str, str],
) -> int:
    response = client.post(
        f"/api/traces/{session_id}/events",
        json={"events": events},
        headers=api_auth,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"POST /api/traces/{session_id}/events failed: "
            f"{response.status_code} {response.text}"
        )
    body = response.json()
    rejected = body.get("rejected") or []
    if rejected:
        raise RuntimeError(f"events rejected for {session_id}: {rejected}")
    return int(body.get("accepted", 0))


def _analyze(
    client: Any, session_id: str, console_auth: dict[str, str]
) -> list[dict[str, Any]]:
    response = client.post(f"/api/traces/{session_id}/analyze", headers=console_auth)
    if response.status_code != 200:
        raise RuntimeError(
            f"POST /api/traces/{session_id}/analyze failed: "
            f"{response.status_code} {response.text}"
        )
    return list(response.json().get("incidents") or [])


def _run_incident_workflows(
    client: Any,
    incident_ids: set[str],
    console_auth: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fix_agent_results: list[dict[str, Any]] = []
    regression_runs: list[dict[str, Any]] = []

    for incident_id in sorted(incident_ids):
        fix_response = client.post(
            f"/api/incidents/{incident_id}/fix-agent",
            json={},
            headers=console_auth,
        )
        if fix_response.status_code != 200:
            raise RuntimeError(
                f"POST /api/incidents/{incident_id}/fix-agent failed: "
                f"{fix_response.status_code} {fix_response.text}"
            )
        fix_body = fix_response.json()
        fix_agent_results.append(fix_body)
        github_pr = fix_body.get("github_pr") or {}
        pr_url = github_pr.get("pr_url") if isinstance(github_pr, dict) else None

        regression_response = client.post(
            f"/api/incidents/{incident_id}/regression-runs",
            json={"pr_url": pr_url, "fallback_profile": "demo"},
            headers=console_auth,
        )
        if regression_response.status_code != 200:
            raise RuntimeError(
                f"POST /api/incidents/{incident_id}/regression-runs failed: "
                f"{regression_response.status_code} {regression_response.text}"
            )
        regression_runs.append(regression_response.json()["regression_run"])

    return fix_agent_results, regression_runs


def seed(
    client: Any,
    *,
    api_key: str = API_KEY,
    console_token: str = CONSOLE_TOKEN,
    run_workflows: bool = True,
) -> dict[str, Any]:
    """Seed deterministic demo sessions through a TestClient-shaped client."""

    api_auth = _auth(api_key)
    console_auth = _auth(console_token)

    sessions_created = 0
    events_accepted = 0
    artifacts_created = 0
    incident_ids: set[str] = set()
    incident_labels: set[str] = set()
    agent_types: set[str] = set()

    for scenario in SCENARIOS:
        for index, goal in enumerate(scenario.goals, start=1):
            session_id = _session_id(scenario.surface, index)
            created_session_id = _create_session(
                client,
                session_id=session_id,
                goal=goal,
                scenario=scenario,
                api_auth=api_auth,
            )
            sessions_created += 1
            agent_types.add(scenario.agent)

            artifacts = _upload_artifacts(
                client,
                session_id=created_session_id,
                scenario=scenario,
                api_auth=api_auth,
            )
            artifacts_created += len(artifacts)

            events = _build_events(
                session_id=created_session_id,
                goal=goal,
                scenario=scenario,
                artifacts=artifacts,
            )
            events_accepted += _post_events(
                client, created_session_id, events, api_auth
            )

            for incident in _analyze(client, created_session_id, console_auth):
                incident_id = incident.get("id")
                if incident_id is not None:
                    incident_ids.add(str(incident_id))
                label = incident.get("label")
                if label is not None:
                    incident_labels.add(str(label))

    fix_agent_results: list[dict[str, Any]] = []
    regression_runs: list[dict[str, Any]] = []
    if run_workflows and incident_ids:
        fix_agent_results, regression_runs = _run_incident_workflows(
            client, incident_ids, console_auth
        )

    return {
        "sessions_created": sessions_created,
        "events_accepted": events_accepted,
        "artifacts_created": artifacts_created,
        "incident_ids": sorted(incident_ids),
        "incident_labels": sorted(incident_labels),
        "agent_types": sorted(agent_types),
        "fix_agent_runs": len(fix_agent_results),
        "regression_runs": len(regression_runs),
    }


def main(argv: list[str] | None = None) -> int:
    """Seed via TestClient or a running API and print a summary."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", help="Running Promptetheus API base URL")
    parser.add_argument("--api-key", default=API_KEY)
    parser.add_argument("--console-token", default=CONSOLE_TOKEN)
    parser.add_argument(
        "--skip-workflows",
        action="store_true",
        help="Only seed traces/events/artifacts; skip fix-agent/regression",
    )
    args = parser.parse_args(argv or [])

    if args.api_url:
        summary = seed(
            HttpApiClient(args.api_url),
            api_key=args.api_key,
            console_token=args.console_token,
            run_workflows=not args.skip_workflows,
        )
    else:
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            print("scripts/seed.py needs FastAPI installed: pip install fastapi httpx.")
            return 1

        from promptetheus.server.app import create_app

        app = create_app()
        with TestClient(app) as client:
            summary = seed(client, run_workflows=not args.skip_workflows)

    print("Promptetheus seed complete:")
    print(f"  sessions created : {summary['sessions_created']}")
    print(f"  events accepted  : {summary['events_accepted']}")
    print(f"  artifacts created: {summary['artifacts_created']}")
    print(f"  incidents formed : {len(summary['incident_ids'])}")
    print(f"  fix-agent runs   : {summary['fix_agent_runs']}")
    print(f"  regression runs  : {summary['regression_runs']}")
    if summary["agent_types"]:
        print(f"  agent types      : {', '.join(summary['agent_types'])}")
    if summary["incident_labels"]:
        print(f"  incident labels  : {', '.join(summary['incident_labels'])}")
    for incident_id in summary["incident_ids"]:
        print(f"    - {incident_id}")

    if not summary["incident_ids"]:
        print("WARNING: no incidents formed; expected at least one.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
