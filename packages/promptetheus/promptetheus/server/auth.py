"""Auth + workspace resolution for the State-0 FastAPI server.

Local development uses deterministic dev credentials. Hosted deployments use
project API-key lookup for ingestion and Supabase Auth JWTs for console reads.
Console JWTs never supply trusted workspace scope directly; the authenticated
``sub`` resolves to workspace membership in Postgres before a principal is
accepted.

Principal kinds (per the locked endpoint table's Auth column):
    - api_key  : SDK ingestion (Authorization: Bearer <project_api_key>)
    - console  : console reads (stands in for a Supabase session JWT)
    - server   : internal writeback (PUT /api/traces/{id}/analysis)
"""

from __future__ import annotations

import hashlib
import importlib
import os
import secrets
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Literal

PrincipalKind = Literal["api_key", "console", "server"]
AuthMode = Literal["dev", "supabase"]
WorkspaceRole = Literal["owner", "member"]

# Deterministic local-dev defaults; override via env in real deployments.
DEV_API_KEY = os.environ.get("PROMPTETHEUS_DEV_API_KEY", "pt_dev_key")
DEV_CONSOLE_TOKEN = os.environ.get("PROMPTETHEUS_CONSOLE_TOKEN", "pt_console_token")
DEV_SERVER_TOKEN = os.environ.get("PROMPTETHEUS_SERVER_TOKEN", "pt_server_token")
DEV_WORKSPACE_ID = os.environ.get("PROMPTETHEUS_DEV_WORKSPACE", "ws_dev")
DEV_PROJECT_ID = os.environ.get("PROMPTETHEUS_DEV_PROJECT", "proj_dev")
DEV_USER_ID = os.environ.get("PROMPTETHEUS_DEV_USER", "user_dev")
DEV_ROLE: WorkspaceRole = "owner"


def auth_mode_from_env() -> AuthMode:
    raw = os.environ.get("PROMPTETHEUS_AUTH_MODE", "dev").strip().lower()
    if raw == "supabase":
        return "supabase"
    return "dev"


def hash_api_key(api_key: str) -> str:
    """Return the stored hash for a project API key (never store the raw key)."""

    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_project_api_key() -> str:
    """Mint a project-scoped live API key. The caller stores only its hash."""

    return f"pt_live_{secrets.token_urlsafe(32)}"


def api_key_preview(api_key: str) -> str:
    """Return a stable masked display value for a raw project API key."""

    prefix = "pt_live"
    suffix = api_key[-6:] if len(api_key) >= 6 else api_key
    return f"{prefix}_...{suffix}"


@dataclass(frozen=True)
class AuthContext:
    """Resolved identity for a request."""

    kind: PrincipalKind
    workspace_id: str
    project_id: str | None = None
    user_id: str | None = None
    role: WorkspaceRole | None = None

    @property
    def is_server(self) -> bool:
        return self.kind == "server"

    @property
    def is_owner(self) -> bool:
        return self.role == "owner" or self.is_server


@dataclass(frozen=True)
class Project:
    project_id: str
    workspace_id: str
    api_key_hash: str
    name: str = "Dev Project"


@dataclass(frozen=True)
class WorkspaceMembership:
    workspace_id: str
    user_id: str
    role: WorkspaceRole


class AuthRegistry:
    """Maps API-key hashes -> project/workspace and validates console/server tokens.

    Seeded with a single dev project so the local stack and tests work out of the
    box. Additional projects can be registered for multi-tenant tests.
    """

    def __init__(
        self,
        project_lookup: Callable[[str], Project | None] | None = None,
        membership_lookup: Callable[
            [str, str | None], WorkspaceMembership | None
        ]
        | None = None,
        *,
        auth_mode: AuthMode | None = None,
        supabase_jwt_secret: str | None = None,
        supabase_jwt_audience: str | None = None,
    ) -> None:
        self._by_key_hash: dict[str, Project] = {}
        self._console_tokens: dict[str, WorkspaceMembership] = {}
        self._server_token = DEV_SERVER_TOKEN
        self._project_lookup = project_lookup
        self._membership_lookup = membership_lookup
        self._auth_mode = auth_mode or auth_mode_from_env()
        self._supabase_jwt_secret = supabase_jwt_secret or os.environ.get(
            "SUPABASE_JWT_SECRET"
        )
        self._supabase_jwt_audience = (
            supabase_jwt_audience
            if supabase_jwt_audience is not None
            else os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated")
        )
        self._bootstrap_dev()

    def _bootstrap_dev(self) -> None:
        self.register_project(
            project_id=DEV_PROJECT_ID,
            workspace_id=DEV_WORKSPACE_ID,
            api_key=DEV_API_KEY,
        )
        self._console_tokens[DEV_CONSOLE_TOKEN] = WorkspaceMembership(
            workspace_id=DEV_WORKSPACE_ID,
            user_id=DEV_USER_ID,
            role=DEV_ROLE,
        )

    def register_project(
        self, *, project_id: str, workspace_id: str, api_key: str
    ) -> Project:
        project = Project(
            project_id=project_id,
            workspace_id=workspace_id,
            api_key_hash=hash_api_key(api_key),
        )
        self._by_key_hash[project.api_key_hash] = project
        return project

    def replace_project_api_key(
        self, *, project_id: str, workspace_id: str, api_key: str
    ) -> Project:
        """Replace an in-memory project credential after hosted key rotation.

        Store-backed lookups already observe the new hash. This keeps the dev
        registry in sync and removes the previous static key for that project.
        """

        self._by_key_hash = {
            key_hash: project
            for key_hash, project in self._by_key_hash.items()
            if project.project_id != project_id
        }
        return self.register_project(
            project_id=project_id,
            workspace_id=workspace_id,
            api_key=api_key,
        )

    def register_console_token(
        self,
        token: str,
        workspace_id: str,
        *,
        user_id: str = DEV_USER_ID,
        role: WorkspaceRole = DEV_ROLE,
    ) -> None:
        self._console_tokens[token] = WorkspaceMembership(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
        )

    def register_console_membership(
        self,
        token: str,
        workspace_id: str,
        *,
        user_id: str = DEV_USER_ID,
        role: WorkspaceRole = DEV_ROLE,
    ) -> None:
        self._console_tokens[token] = WorkspaceMembership(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
        )

    def resolve(
        self, authorization: str | None, *, workspace_id: str | None = None
    ) -> AuthContext | None:
        """Resolve an Authorization header value to an AuthContext.

        Returns None when the credential is missing or unrecognized (the API
        layer maps that to 401). Workspace/project mismatch (403) is the
        API layer's job, using the returned context.
        """

        token = _bearer(authorization)
        if not token:
            return None

        if token == self._server_token:
            # Server principal is workspace-agnostic; the caller supplies scope.
            return AuthContext(
                kind="server",
                workspace_id=workspace_id or DEV_WORKSPACE_ID,
                role="owner",
            )

        if self._auth_mode == "dev":
            membership = self._console_tokens.get(token)
            if membership is not None and _workspace_matches(
                membership.workspace_id, workspace_id
            ):
                return AuthContext(
                    kind="console",
                    workspace_id=membership.workspace_id,
                    user_id=membership.user_id,
                    role=membership.role,
                )
        else:
            membership = self._resolve_supabase_console(token, workspace_id)
            if membership is not None:
                return AuthContext(
                    kind="console",
                    workspace_id=membership.workspace_id,
                    user_id=membership.user_id,
                    role=membership.role,
                )

        project = self._by_key_hash.get(hash_api_key(token))
        if project is not None:
            return AuthContext(
                kind="api_key",
                workspace_id=project.workspace_id,
                project_id=project.project_id,
            )
        if self._project_lookup is not None:
            project = self._project_lookup(token)
            if project is not None:
                return AuthContext(
                    kind="api_key",
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                )
        return None

    def _resolve_supabase_console(
        self, token: str, workspace_id: str | None
    ) -> WorkspaceMembership | None:
        if not self._supabase_jwt_secret or self._membership_lookup is None:
            return None
        try:
            payload = _decode_supabase_jwt(
                token,
                secret=self._supabase_jwt_secret,
                audience=self._supabase_jwt_audience,
            )
        except ValueError:
            return None
        user_id = payload.get("sub")
        if not isinstance(user_id, str) or not user_id:
            return None
        return self._membership_lookup(user_id, workspace_id)


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip() or None


def _workspace_matches(actual: str, requested: str | None) -> bool:
    return requested is None or requested == "" or actual == requested


def _decode_supabase_jwt(
    token: str, *, secret: str, audience: str | None
) -> dict[str, Any]:
    """Decode a Supabase HS256 JWT through PyJWT without a hard import at module load."""

    try:
        jwt = importlib.import_module("jwt")
    except Exception as exc:  # pragma: no cover - dependency guard
        raise ValueError("PyJWT is required for Supabase auth mode") from exc

    options: dict[str, bool] = {}
    kwargs: dict[str, Any] = {
        "key": secret,
        "algorithms": ["HS256"],
        "options": options,
    }
    if audience:
        kwargs["audience"] = audience
    else:
        options["verify_aud"] = False
    try:
        payload = jwt.decode(token, **kwargs)
    except Exception as exc:
        raise ValueError("invalid Supabase JWT") from exc
    if not isinstance(payload, dict):
        raise ValueError("Supabase JWT payload must be an object")
    return dict(payload)
