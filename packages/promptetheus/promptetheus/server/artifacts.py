"""Artifact byte storage for replay screenshots and recordings.

FastAPI owns artifact identity and metadata; this module owns the bytes behind
that identity. Local development writes to disk while hosted deployments can
switch to Supabase Storage without changing the route or Store contracts.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class StoredArtifact:
    storage_path: str
    size_bytes: int


class ArtifactStorage(Protocol):
    def put(
        self,
        *,
        workspace_id: str,
        session_id: str,
        artifact_id: str,
        filename: str,
        body: bytes,
        content_type: str,
    ) -> StoredArtifact: ...

    def signed_url(self, storage_path: str, *, expires_in: int = 300) -> str: ...

    def delete(self, storage_path: str) -> bool: ...


def safe_artifact_filename(filename: str | None) -> str:
    """Return a storage-safe filename while preserving useful extensions."""

    raw = (filename or "artifact.bin").strip() or "artifact.bin"
    name = PurePosixPath(raw.replace("\\", "/")).name
    if name in ("", ".", ".."):
        return "artifact.bin"
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in name)


def artifact_storage_path(
    *,
    workspace_id: str,
    session_id: str,
    artifact_id: str,
    filename: str,
) -> str:
    return f"artifacts/{workspace_id}/{session_id}/{artifact_id}/{filename}"


class LocalArtifactStorage:
    """Filesystem-backed artifact storage for tests and local development."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        signed_base_url: str = "https://artifacts.local/signed",
    ) -> None:
        self.root = Path(root or os.environ.get("PROMPTETHEUS_ARTIFACT_DIR", "/tmp/promptetheus-artifacts"))
        self.signed_base_url = signed_base_url.rstrip("/")

    def put(
        self,
        *,
        workspace_id: str,
        session_id: str,
        artifact_id: str,
        filename: str,
        body: bytes,
        content_type: str,
    ) -> StoredArtifact:
        storage_path = artifact_storage_path(
            workspace_id=workspace_id,
            session_id=session_id,
            artifact_id=artifact_id,
            filename=filename,
        )
        destination = self.root / storage_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        return StoredArtifact(storage_path=storage_path, size_bytes=len(body))

    def signed_url(self, storage_path: str, *, expires_in: int = 300) -> str:
        quoted_path = quote(storage_path, safe="/")
        return f"{self.signed_base_url}/{quoted_path}?token=dev&expires_in={expires_in}"

    def delete(self, storage_path: str) -> bool:
        path = self.root / storage_path
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

class SupabaseArtifactStorage:
    """Supabase Storage implementation using the Storage REST API."""

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        bucket: str,
        timeout: float = 10.0,
    ) -> None:
        self.supabase_url = supabase_url.rstrip("/") + "/"
        self.service_role_key = service_role_key
        self.bucket = bucket.strip("/")
        self.timeout = timeout

    def put(
        self,
        *,
        workspace_id: str,
        session_id: str,
        artifact_id: str,
        filename: str,
        body: bytes,
        content_type: str,
    ) -> StoredArtifact:
        storage_path = artifact_storage_path(
            workspace_id=workspace_id,
            session_id=session_id,
            artifact_id=artifact_id,
            filename=filename,
        )
        url = urljoin(
            self.supabase_url,
            f"storage/v1/object/{self.bucket}/{quote(storage_path, safe='/')}",
        )
        request = Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.service_role_key}",
                "apikey": self.service_role_key,
                "Content-Type": content_type,
                "x-upsert": "true",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout):
                pass
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase artifact upload failed: {exc.code} {detail}") from exc
        return StoredArtifact(storage_path=storage_path, size_bytes=len(body))

    def signed_url(self, storage_path: str, *, expires_in: int = 300) -> str:
        url = urljoin(
            self.supabase_url,
            f"storage/v1/object/sign/{self.bucket}/{quote(storage_path, safe='/')}",
        )
        payload = json.dumps({"expiresIn": expires_in}).encode("utf-8")
        request = Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.service_role_key}",
                "apikey": self.service_role_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase signed URL failed: {exc.code} {detail}") from exc
        signed_url = body.get("signedURL") or body.get("signedUrl") or body.get("url")
        if not isinstance(signed_url, str) or not signed_url:
            raise RuntimeError("Supabase signed URL response missing URL")
        if signed_url.startswith("http"):
            return signed_url
        return urljoin(self.supabase_url, signed_url.lstrip("/"))

    def delete(self, storage_path: str) -> bool:
        url = urljoin(
            self.supabase_url,
            f"storage/v1/object/{self.bucket}",
        )
        payload = json.dumps({"prefixes": [storage_path]}).encode("utf-8")
        request = Request(
            url,
            data=payload,
            method="DELETE",
            headers={
                "Authorization": f"Bearer {self.service_role_key}",
                "apikey": self.service_role_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout):
                pass
        except HTTPError as exc:
            if exc.code == 404:
                return False
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase artifact delete failed: {exc.code} {detail}") from exc
        return True


def artifact_storage_from_env() -> ArtifactStorage:
    backend = os.environ.get("PROMPTETHEUS_ARTIFACT_STORAGE", "local").strip().lower()
    if backend == "supabase":
        supabase_url = os.environ.get("SUPABASE_URL")
        service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        bucket = os.environ.get("PROMPTETHEUS_SUPABASE_ARTIFACT_BUCKET", "artifacts")
        if not supabase_url or not service_role_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for "
                "PROMPTETHEUS_ARTIFACT_STORAGE=supabase"
            )
        return SupabaseArtifactStorage(
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            bucket=bucket,
        )
    return LocalArtifactStorage()


__all__ = [
    "ArtifactStorage",
    "LocalArtifactStorage",
    "StoredArtifact",
    "SupabaseArtifactStorage",
    "artifact_storage_from_env",
    "artifact_storage_path",
    "safe_artifact_filename",
]
