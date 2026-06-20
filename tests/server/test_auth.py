"""Unit tests for server/auth.py: principal resolution + key hashing.

AuthRegistry is the State-0 stand-in for Supabase Auth + project-API-key
lookup. These tests pin the resolution contract (api_key / console / server /
invalid) and the determinism of hash_api_key (raw keys are never stored).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server.auth import (  # noqa: E402
    AuthContext,
    AuthRegistry,
    Project,
    WorkspaceMembership,
    api_key_preview,
    generate_project_api_key,
    hash_api_key,
)


# ---------------------------------------------------------------------------
# hash_api_key
# ---------------------------------------------------------------------------


def test_hash_api_key_is_deterministic() -> None:
    first = hash_api_key("pt_dev_key")
    second = hash_api_key("pt_dev_key")
    assert first == second


def test_hash_api_key_differs_per_key_and_never_returns_raw() -> None:
    a = hash_api_key("pt_dev_key")
    b = hash_api_key("pt_other_key")
    assert a != b
    # The stored hash must not be the raw key, and must be a sha256 hexdigest.
    assert a != "pt_dev_key"
    assert len(a) == 64
    assert all(char in "0123456789abcdef" for char in a)


def test_generate_project_api_key_and_preview_are_safe() -> None:
    raw = generate_project_api_key()
    preview = api_key_preview(raw)

    assert raw.startswith("pt_live_")
    assert preview.startswith("pt_live_...")
    assert raw != preview
    assert preview.endswith(raw[-6:])


# ---------------------------------------------------------------------------
# AuthRegistry.resolve
# ---------------------------------------------------------------------------


def test_resolve_api_key_principal() -> None:
    registry = AuthRegistry()
    ctx = registry.resolve("Bearer pt_dev_key")
    assert isinstance(ctx, AuthContext)
    assert ctx.kind == "api_key"
    assert ctx.workspace_id == "ws_dev"
    assert ctx.project_id == "proj_dev"
    assert ctx.is_server is False


def test_resolve_console_principal() -> None:
    registry = AuthRegistry()
    ctx = registry.resolve("Bearer pt_console_token")
    assert ctx is not None
    assert ctx.kind == "console"
    assert ctx.workspace_id == "ws_dev"
    # Console principals are not scoped to a single project.
    assert ctx.project_id is None
    assert ctx.is_server is False


def test_resolve_server_principal() -> None:
    registry = AuthRegistry()
    ctx = registry.resolve("Bearer pt_server_token")
    assert ctx is not None
    assert ctx.kind == "server"
    assert ctx.is_server is True


def test_resolve_invalid_or_missing_credential_is_none() -> None:
    registry = AuthRegistry()
    assert registry.resolve(None) is None
    assert registry.resolve("") is None
    assert registry.resolve("Bearer ") is None
    assert registry.resolve("Bearer wrong_key") is None


def test_resolve_accepts_bearer_case_insensitively() -> None:
    registry = AuthRegistry()
    ctx = registry.resolve("bearer pt_dev_key")
    assert ctx is not None
    assert ctx.kind == "api_key"


def test_register_project_routes_to_its_workspace() -> None:
    registry = AuthRegistry()
    registry.register_project(
        project_id="proj_other", workspace_id="ws_other", api_key="pt_other_key"
    )
    ctx = registry.resolve("Bearer pt_other_key")
    assert ctx is not None
    assert ctx.kind == "api_key"
    assert ctx.workspace_id == "ws_other"
    assert ctx.project_id == "proj_other"


def test_resolve_uses_hosted_project_lookup_after_dev_keys() -> None:
    def lookup(api_key: str) -> Project | None:
        if api_key != "pt_hosted_key":
            return None
        return Project(
            project_id="proj_hosted",
            workspace_id="ws_hosted",
            api_key_hash=hash_api_key(api_key),
            name="Hosted Project",
        )

    registry = AuthRegistry(project_lookup=lookup)
    ctx = registry.resolve("Bearer pt_hosted_key")
    assert ctx is not None
    assert ctx.kind == "api_key"
    assert ctx.workspace_id == "ws_hosted"
    assert ctx.project_id == "proj_hosted"


def test_register_console_token_routes_to_its_workspace() -> None:
    registry = AuthRegistry()
    registry.register_console_token("pt_other_console", "ws_other")
    ctx = registry.resolve("Bearer pt_other_console")
    assert ctx is not None
    assert ctx.kind == "console"
    assert ctx.workspace_id == "ws_other"


def test_register_console_token_can_pin_member_role() -> None:
    registry = AuthRegistry()
    registry.register_console_token(
        "pt_member_console", "ws_dev", user_id="user_member", role="member"
    )
    ctx = registry.resolve("Bearer pt_member_console")
    assert ctx is not None
    assert ctx.user_id == "user_member"
    assert ctx.role == "member"
    assert ctx.is_owner is False


def test_supabase_jwt_resolves_through_membership_lookup() -> None:
    secret = "test-secret-that-is-at-least-32-bytes"
    user_id = "00000000-0000-0000-0000-000000000123"
    token = jwt.encode(
        {
            "sub": user_id,
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )

    def lookup(
        lookup_user_id: str, workspace_id: str | None
    ) -> WorkspaceMembership | None:
        assert lookup_user_id == user_id
        assert workspace_id == "ws_hosted"
        return WorkspaceMembership(
            user_id=user_id, workspace_id="ws_hosted", role="owner"
        )

    registry = AuthRegistry(
        auth_mode="supabase",
        supabase_jwt_secret=secret,
        membership_lookup=lookup,
    )
    ctx = registry.resolve(
        f"Bearer {token}", workspace_id="ws_hosted"
    )

    assert ctx is not None
    assert ctx.kind == "console"
    assert ctx.user_id == user_id
    assert ctx.workspace_id == "ws_hosted"
    assert ctx.role == "owner"


def test_supabase_jwt_without_membership_is_invalid() -> None:
    secret = "test-secret-that-is-at-least-32-bytes"
    token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000123",
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )
    registry = AuthRegistry(
        auth_mode="supabase",
        supabase_jwt_secret=secret,
        membership_lookup=lambda _user_id, _workspace_id: None,
    )

    assert registry.resolve(f"Bearer {token}") is None


def test_supabase_jwt_wrong_audience_is_invalid() -> None:
    secret = "test-secret-that-is-at-least-32-bytes"
    token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000123",
            "aud": "wrong",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )
    registry = AuthRegistry(
        auth_mode="supabase",
        supabase_jwt_secret=secret,
        membership_lookup=lambda _user_id, _workspace_id: WorkspaceMembership(
            user_id="user", workspace_id="ws", role="owner"
        ),
    )

    assert registry.resolve(f"Bearer {token}") is None
