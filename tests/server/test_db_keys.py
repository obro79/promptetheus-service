from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server.auth import hash_api_key  # noqa: E402
from promptetheus.server.db.keys import (  # noqa: E402
    ProjectRecord,
    lookup_project_by_api_key,
)


class FakeProjectLookupStore:
    def __init__(self) -> None:
        self.seen_hash: str | None = None

    def lookup_project_by_api_key_hash(self, api_key_hash: str) -> ProjectRecord | None:
        self.seen_hash = api_key_hash
        if api_key_hash != hash_api_key("pt_hosted_key"):
            return None
        return ProjectRecord(
            project_id="proj_hosted",
            workspace_id="ws_hosted",
            api_key_hash=api_key_hash,
            name="Hosted Project",
        )


def test_lookup_project_by_api_key_uses_store_hash_lookup() -> None:
    store = FakeProjectLookupStore()

    project = lookup_project_by_api_key(store, "pt_hosted_key")

    assert project is not None
    assert store.seen_hash == hash_api_key("pt_hosted_key")
    assert project.project_id == "proj_hosted"
    assert project.workspace_id == "ws_hosted"


def test_lookup_project_by_api_key_returns_none_without_lookup_hook() -> None:
    assert lookup_project_by_api_key(object(), "pt_hosted_key") is None
