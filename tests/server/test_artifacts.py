from __future__ import annotations

import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server import create_app  # noqa: E402
from promptetheus.server.artifacts import (  # noqa: E402
    LocalArtifactStorage,
    SupabaseArtifactStorage,
    artifact_storage_path,
    safe_artifact_filename,
)
import promptetheus.server.artifacts as artifacts_mod  # noqa: E402

KEY_AUTH = {"Authorization": "Bearer pt_dev_key"}
CONSOLE_AUTH = {"Authorization": "Bearer pt_console_token"}
SERVER_AUTH = {"Authorization": "Bearer pt_server_token"}


def _create_trace(client: testclient.TestClient, trace_id: str = "trace_art") -> str:
    response = client.post(
        "/api/traces",
        json={"id": trace_id, "user_goal": "capture replay"},
        headers=KEY_AUTH,
    )
    assert response.status_code == 201
    return response.json()["trace"]["id"]


def test_safe_artifact_filename_strips_paths_and_unsafe_chars() -> None:
    assert safe_artifact_filename("../nested/step one.png") == "step_one.png"
    assert safe_artifact_filename("..") == "artifact.bin"


def test_local_artifact_storage_writes_bytes_and_signs(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)

    stored = storage.put(
        workspace_id="ws_dev",
        session_id="trace_1",
        artifact_id="artifact_1",
        filename="step.png",
        body=b"PNG",
        content_type="image/png",
    )

    assert stored.storage_path == "artifacts/ws_dev/trace_1/artifact_1/step.png"
    assert stored.size_bytes == 3
    assert (tmp_path / stored.storage_path).read_bytes() == b"PNG"
    assert storage.signed_url(stored.storage_path).startswith(
        "https://artifacts.local/signed/artifacts/ws_dev/trace_1/"
    )
    storage.delete(stored.storage_path)
    assert not (tmp_path / stored.storage_path).exists()


def test_supabase_artifact_storage_delete_calls_storage_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[artifacts_mod.Request] = []

    class _Response:
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_urlopen(
        request: artifacts_mod.Request, timeout: float
    ) -> _Response:
        requests.append(request)
        assert timeout == 10.0
        return _Response()

    monkeypatch.setattr(artifacts_mod, "urlopen", fake_urlopen)
    storage = SupabaseArtifactStorage(
        supabase_url="https://example.supabase.co",
        service_role_key="service-role",
        bucket="artifacts",
    )

    deleted = storage.delete("artifacts/ws/sess/artifact/file.webm")

    assert deleted is True
    assert requests
    assert requests[0].get_method() == "DELETE"
    assert (
        requests[0].full_url
        == "https://example.supabase.co/storage/v1/object/artifacts"
    )
    assert json.loads(requests[0].data.decode("utf-8")) == (
        {"prefixes": ["artifacts/ws/sess/artifact/file.webm"]}
    )


def test_binary_artifact_upload_stores_bytes_and_returns_signed_url(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)
    client = testclient.TestClient(create_app(artifact_storage=storage))
    session_id = _create_trace(client)

    response = client.post(
        f"/api/traces/{session_id}/artifacts",
        content=b"PNG",
        headers={
            **KEY_AUTH,
            "Content-Type": "image/png",
            "X-Promptetheus-Filename": "../step one.png",
            "X-Promptetheus-Artifact-Type": "screenshot",
        },
    )

    assert response.status_code == 201
    artifact = response.json()["artifact"]
    assert artifact["artifact_type"] == "screenshot"
    assert artifact["content_type"] == "image/png"
    assert artifact["size_bytes"] == 3
    assert artifact["storage_path"].endswith("/step_one.png")
    assert (tmp_path / artifact["storage_path"]).read_bytes() == b"PNG"

    redirect = client.get(
        f"/artifacts/{artifact['artifact_id']}",
        headers=CONSOLE_AUTH,
        follow_redirects=False,
    )
    assert redirect.status_code == 307
    assert redirect.headers["location"].startswith("https://artifacts.local/signed/")

    signed = client.get(
        f"/artifacts/{artifact['artifact_id']}?format=json", headers=CONSOLE_AUTH
    )
    assert signed.status_code == 200
    assert signed.json()["signed_url"].startswith("https://artifacts.local/signed/")


def test_metadata_only_artifact_keeps_existing_storage_identity(
    tmp_path: Path,
) -> None:
    client = testclient.TestClient(
        create_app(artifact_storage=LocalArtifactStorage(tmp_path))
    )
    session_id = _create_trace(client, "trace_meta")

    response = client.post(
        f"/api/traces/{session_id}/artifacts",
        json={"content_type": "image/png", "filename": "ok.png", "size_bytes": 5},
        headers=KEY_AUTH,
    )

    assert response.status_code == 201
    artifact = response.json()["artifact"]
    assert artifact["storage_path"] == artifact_storage_path(
        workspace_id="ws_dev",
        session_id=session_id,
        artifact_id=artifact["artifact_id"],
        filename="ok.png",
    )
    assert not (tmp_path / artifact["storage_path"]).exists()


def test_retention_cleanup_dry_run_and_execute(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    client = testclient.TestClient(create_app(artifact_storage=storage))
    session_id = _create_trace(client, "trace_expired")
    old = datetime.now(timezone.utc) - timedelta(days=3)
    client.app.state.store.update_session(
        session_id,
        {"started_at": old.strftime("%Y-%m-%dT%H:%M:%SZ")},
    )
    client.app.state.store.update_project("proj_dev", {"retention_days": 1})

    uploaded = client.post(
        f"/api/traces/{session_id}/artifacts",
        content=b"WEBM",
        headers={
            **KEY_AUTH,
            "Content-Type": "video/webm",
            "X-Promptetheus-Filename": "replay.webm",
        },
    )
    assert uploaded.status_code == 201
    artifact = uploaded.json()["artifact"]
    assert (tmp_path / artifact["storage_path"]).exists()

    dry = client.post(
        "/internal/retention/run",
        json={"dry_run": True, "limit": 10},
        headers=SERVER_AUTH,
    )
    assert dry.status_code == 200
    assert dry.json()["retention"]["sessions_matched"] == 1
    assert dry.json()["retention"]["sessions_deleted"] == 0
    assert (tmp_path / artifact["storage_path"]).exists()

    executed = client.post(
        "/internal/retention/run",
        json={"dry_run": False, "limit": 10},
        headers=SERVER_AUTH,
    )
    assert executed.status_code == 200
    result = executed.json()["retention"]
    assert result["sessions_deleted"] == 1
    assert result["artifacts_deleted"] == 1
    assert not (tmp_path / artifact["storage_path"]).exists()
    assert client.get(f"/api/traces/{session_id}/events", headers=CONSOLE_AUTH).status_code == 404
