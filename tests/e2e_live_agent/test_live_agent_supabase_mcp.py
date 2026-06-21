"""Optional live E2E: SDK agent -> FastAPI -> Supabase Postgres -> MCP.

This suite is intentionally skipped unless explicitly enabled. It writes to the
database URL provided by PROMPTETHEUS_LIVE_DATABASE_URL, so use a non-production
hosted Supabase project.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server.mcp import server as mcp_tools  # noqa: E402
from promptetheus.server.mcp.client import PromptetheusClient  # noqa: E402

EXPECTED_TYPES = [
    "state_change",
    "user_message",
    "browser_action",
    "dom_snapshot",
    "browser_action",
    "agent_message",
    "goal_check",
    "session_end",
]

SECRET_TOKEN = "sk-live-e2e-demo-secret-123456"
SECRET_PASSWORD = "live-e2e-password"
DEFAULT_SDK_PATH = (
    "/Users/owenfisher/Desktop/projects/promptetheus-sdk/packages/promptetheus"
)


def _live_env() -> dict[str, str]:
    if os.environ.get("PROMPTETHEUS_LIVE_E2E") != "1":
        pytest.skip("set PROMPTETHEUS_LIVE_E2E=1 to run hosted Supabase E2E")

    required = {
        "PROMPTETHEUS_LIVE_DATABASE_URL": os.environ.get(
            "PROMPTETHEUS_LIVE_DATABASE_URL"
        ),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        pytest.skip(f"missing live E2E env: {', '.join(missing)}")

    sdk_path = Path(os.environ.get("PROMPTETHEUS_SDK_PATH", DEFAULT_SDK_PATH)).resolve()
    if not sdk_path.exists():
        pytest.skip(f"PROMPTETHEUS_SDK_PATH does not exist: {sdk_path}")

    return {
        **{name: str(value) for name, value in required.items()},
        "PROMPTETHEUS_SDK_PATH": str(sdk_path),
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(api_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 20
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError(
                f"live E2E service exited early\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            with urlopen(f"{api_url}/health", timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError) as exc:
            last_error = exc
        time.sleep(0.2)
    raise AssertionError(f"live E2E service did not become healthy: {last_error}")


def _start_service(env: dict[str, str], api_url: str) -> subprocess.Popen[str]:
    pytest.importorskip("uvicorn")
    port = api_url.rsplit(":", 1)[1]
    pythonpath = os.pathsep.join(
        [
            str(Path(__file__).resolve().parents[2]),
            str(PACKAGE_ROOT),
            env.get("PYTHONPATH", ""),
        ]
    )
    service_env = {**env, "PYTHONPATH": pythonpath}
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.e2e_live_agent.live_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            port,
            "--log-level",
            "warning",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=service_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for_health(api_url, process)
    return process


def _stop_service(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)


def _connect(db_url: str):
    psycopg = pytest.importorskip("psycopg")
    rows = pytest.importorskip("psycopg.rows")
    return psycopg.connect(db_url, row_factory=rows.dict_row)


def _seed_project(
    db_url: str, *, workspace_id: str, project_id: str, api_key: str
) -> None:
    with _connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workspace (id, name) VALUES (%s, %s)",
                (workspace_id, "Live E2E Workspace"),
            )
            cur.execute(
                """
                INSERT INTO project (id, workspace_id, name, api_key_hash)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    project_id,
                    workspace_id,
                    "Live E2E Project",
                    hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
                ),
            )
        conn.commit()


def _cleanup_workspace(db_url: str, workspace_id: str) -> None:
    if os.environ.get("PROMPTETHEUS_E2E_KEEP_ROWS") == "1":
        return
    with _connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM workspace WHERE id = %s", (workspace_id,))
        conn.commit()


def _fetch_events(db_url: str, trace_id: str) -> list[dict]:
    with _connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT seq, type, session_id, timestamp, payload
                FROM trace_event
                WHERE session_id = %s
                ORDER BY seq
                """,
                (trace_id,),
            )
            return [dict(row) for row in cur.fetchall()]


def _poll_events(db_url: str, trace_id: str) -> list[dict]:
    deadline = time.monotonic() + 20
    events: list[dict] = []
    while time.monotonic() < deadline:
        events = _fetch_events(db_url, trace_id)
        if [event["type"] for event in events] == EXPECTED_TYPES:
            return events
        time.sleep(0.5)
    raise AssertionError(f"expected {EXPECTED_TYPES}, got {[e['type'] for e in events]}")


def _run_sdk_agent(env: dict[str, str]) -> None:
    sdk_path = str(Path(env["PROMPTETHEUS_SDK_PATH"]).resolve())
    pythonpath = os.pathsep.join([sdk_path, env.get("PYTHONPATH", "")])
    run_env = {**env, "PYTHONPATH": pythonpath}
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("sdk_agent.py"))],
        cwd=Path(__file__).resolve().parents[2],
        env=run_env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        "SDK live-agent subprocess failed\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_live_sdk_agent_writes_supabase_and_mcp_reads_back() -> None:
    live = _live_env()
    httpx = pytest.importorskip("httpx")

    suffix = uuid.uuid4().hex[:12]
    workspace_id = f"ws_live_e2e_{suffix}"
    project_id = f"proj_live_e2e_{suffix}"
    trace_id = f"trace_live_e2e_{suffix}"
    api_key = f"pt_live_e2e_{suffix}"
    console_token = f"pt_console_e2e_{suffix}"
    api_url = f"http://127.0.0.1:{_free_port()}"
    db_url = live["PROMPTETHEUS_LIVE_DATABASE_URL"]

    env = {
        **os.environ,
        **live,
        "PROMPTETHEUS_E2E_WORKSPACE_ID": workspace_id,
        "PROMPTETHEUS_E2E_PROJECT_ID": project_id,
        "PROMPTETHEUS_E2E_TRACE_ID": trace_id,
        "PROMPTETHEUS_E2E_API_KEY": api_key,
        "PROMPTETHEUS_E2E_CONSOLE_TOKEN": console_token,
        "PROMPTETHEUS_E2E_API_URL": api_url,
        "PROMPTETHEUS_E2E_SECRET_TOKEN": SECRET_TOKEN,
        "PROMPTETHEUS_E2E_SECRET_PASSWORD": SECRET_PASSWORD,
    }

    process: subprocess.Popen[str] | None = None
    try:
        _seed_project(db_url, workspace_id=workspace_id, project_id=project_id, api_key=api_key)
        process = _start_service(env, api_url)
        _run_sdk_agent(env)

        raw_events = _poll_events(db_url, trace_id)
        assert {event["session_id"] for event in raw_events} == {trace_id}
        raw_serialized = json.dumps(raw_events, default=str)
        assert SECRET_TOKEN in raw_serialized
        assert SECRET_PASSWORD in raw_serialized

        analysis = httpx.post(
            f"{api_url}/api/traces/{trace_id}/analyze",
            headers={"Authorization": f"Bearer {console_token}"},
            timeout=10,
        )
        assert analysis.status_code == 200, analysis.text
        incidents = analysis.json()["incidents"]
        assert incidents
        incident_id = incidents[0]["id"]

        mcp_client = PromptetheusClient(base_url=api_url, api_key=api_key)
        try:
            timeline = mcp_tools.get_trace_events(mcp_client, trace_id)
            assert [event["type"] for event in timeline["events"]] == EXPECTED_TYPES
            redacted_timeline = json.dumps(timeline, default=str)
            assert SECRET_TOKEN not in redacted_timeline
            assert SECRET_PASSWORD not in redacted_timeline
            assert "[REDACTED]" in redacted_timeline

            similar = mcp_tools.search_similar_incidents(mcp_client, "browser")
            assert any(incident["id"] == incident_id for incident in similar["incidents"])

            evidence = mcp_tools.get_failure_evidence(mcp_client, incident_id)
            assert "browser_goal_mismatch" in evidence["labels"]
            assert evidence["events"]
            redacted_evidence = json.dumps(evidence, default=str)
            assert SECRET_TOKEN not in redacted_evidence
            assert SECRET_PASSWORD not in redacted_evidence
        finally:
            mcp_client.close()
    finally:
        if process is not None:
            _stop_service(process)
        _cleanup_workspace(db_url, workspace_id)
