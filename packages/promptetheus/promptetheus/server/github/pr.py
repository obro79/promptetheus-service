"""GitHub App pull-request creation for fix-agent output.

The real path is deliberately small and mockable:

1. validate the generated diff stays inside allowed paths;
2. exchange a GitHub App JWT for an installation token;
3. create a ``promptetheus/`` branch from the default branch;
4. write files represented by new-file unified diffs;
5. open a pull request with incident evidence in the body.

When GitHub is disabled, misconfigured, or explicitly forced into fallback mode,
the module returns a labeled PR preview. It never invents a fake GitHub URL.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from promptetheus.server.fix_agent.runner import _changed_paths, _path_inside
from promptetheus.server.models import FixAgentResult


class GitHubTransport(Protocol):
    """Minimal HTTP seam used by tests and the real GitHub REST client."""

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GitHubConfig:
    """Runtime configuration for a GitHub App installation."""

    app_id: str | None = None
    private_key: str | None = None
    installation_id: str | None = None
    repo: str | None = None
    default_branch: str = "main"
    allowed_paths: list[str] = field(default_factory=lambda: ["agents/"])
    branch_prefix: str = "promptetheus"
    enabled: bool = False
    fallback: bool = False

    @classmethod
    def from_env(cls) -> "GitHubConfig":
        allowed_paths = _json_list_env("PROMPTETHEUS_ALLOWED_PATHS") or ["agents/"]
        return cls(
            app_id=os.environ.get("GITHUB_APP_ID"),
            private_key=_private_key_from_env(),
            installation_id=os.environ.get("GITHUB_APP_INSTALLATION_ID"),
            repo=os.environ.get("PROMPTETHEUS_DEMO_REPO"),
            default_branch=os.environ.get("PROMPTETHEUS_DEMO_REPO_BRANCH", "main"),
            allowed_paths=allowed_paths,
            branch_prefix=os.environ.get("PROMPTETHEUS_BRANCH_PREFIX", "promptetheus"),
            enabled=github_pr_enabled(),
            fallback=github_fallback_forced(),
        )

    @property
    def complete(self) -> bool:
        return bool(
            self.app_id
            and self.private_key
            and self.installation_id
            and self.repo
        )


@dataclass(frozen=True)
class GitHubPullRequestResult:
    """Result attached to a fix-agent dispatch."""

    branch: str
    body: str
    changed_files: list[str]
    fallback: bool
    metadata: dict[str, Any]
    pr_url: str | None = None
    title: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "body": self.body,
            "changed_files": list(self.changed_files),
            "fallback": self.fallback,
            "metadata": dict(self.metadata),
            "pr_url": self.pr_url,
            "title": self.title,
        }


class HttpxGitHubTransport:
    """GitHub REST transport, imported lazily to keep server import light."""

    def __init__(self, *, base_url: str = "https://api.github.com") -> None:
        try:
            import httpx
        except Exception as exc:  # pragma: no cover - optional dependency guard
            raise RuntimeError(
                "GitHub PR creation requires httpx. Install the server extras."
            ) from exc
        self._httpx = httpx
        self._base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        response = self._httpx.request(
            method,
            url,
            headers=headers,
            json=json_body,
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"GitHub API {method} {path} failed with {response.status_code}: "
                f"{response.text[:400]}"
            )
        if not response.content:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            return {"value": data}
        return data


def github_pr_enabled() -> bool:
    raw = os.environ.get("PROMPTETHEUS_GITHUB_ENABLED", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def github_fallback_forced() -> bool:
    raw = os.environ.get("PROMPTETHEUS_GITHUB_FALLBACK", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def create_pull_request(
    *,
    fix_result: FixAgentResult,
    incident: dict[str, Any],
    bundle: dict[str, Any],
    config: GitHubConfig | None = None,
    transport: GitHubTransport | None = None,
) -> GitHubPullRequestResult | None:
    """Open a PR for fix_result, or return a labeled fallback preview.

    Returns None when GitHub PR handling is disabled and no fallback preview is
    forced. This lets local fix-agent dispatch remain lightweight by default.
    """

    config = config or GitHubConfig.from_env()
    diff = fix_result.diff or ""
    changed_files = _validate_changed_files(
        diff,
        _allowed_paths(config=config, bundle=bundle),
    )
    branch = _branch_name(config, incident)
    title = _pr_title(incident)
    body = _pr_body(incident=incident, bundle=bundle, fix_result=fix_result)

    if config.fallback:
        return _fallback_preview(
            branch=branch,
            body=body,
            changed_files=changed_files,
            title=title,
            reason="PROMPTETHEUS_GITHUB_FALLBACK is enabled",
        )
    if not config.enabled:
        return None
    if not config.complete:
        return _fallback_preview(
            branch=branch,
            body=body,
            changed_files=changed_files,
            title=title,
            reason="GitHub App environment is incomplete",
        )

    transport = transport or HttpxGitHubTransport()
    jwt = _github_app_jwt(config)
    install_headers = _github_headers(jwt)
    token_response = transport.request(
        "POST",
        f"/app/installations/{config.installation_id}/access_tokens",
        headers=install_headers,
    )
    token = token_response.get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("GitHub installation token response missing token")

    auth_headers = _github_headers(token)
    repo = str(config.repo)
    base_ref = transport.request(
        "GET",
        f"/repos/{repo}/git/ref/heads/{config.default_branch}",
        headers=auth_headers,
    )
    base_sha = _nested(base_ref, ["object", "sha"])
    if not isinstance(base_sha, str) or not base_sha:
        raise RuntimeError("GitHub default branch response missing object.sha")

    transport.request(
        "POST",
        f"/repos/{repo}/git/refs",
        headers=auth_headers,
        json_body={"ref": f"refs/heads/{branch}", "sha": base_sha},
    )

    for path, content in _new_files_from_diff(diff).items():
        transport.request(
            "PUT",
            f"/repos/{repo}/contents/{path}",
            headers=auth_headers,
            json_body={
                "message": f"Promptetheus fix for {incident.get('id')}",
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch,
            },
        )

    pr = transport.request(
        "POST",
        f"/repos/{repo}/pulls",
        headers=auth_headers,
        json_body={
            "title": title,
            "head": branch,
            "base": config.default_branch,
            "body": body,
        },
    )
    pr_url = pr.get("html_url")
    if not isinstance(pr_url, str) or not pr_url:
        raise RuntimeError("GitHub pull request response missing html_url")

    return GitHubPullRequestResult(
        branch=branch,
        body=body,
        changed_files=changed_files,
        fallback=False,
        metadata={"provider": "github", "repo": repo, "default_branch": config.default_branch},
        pr_url=pr_url,
        title=title,
    )


def _fallback_preview(
    *,
    branch: str,
    body: str,
    changed_files: list[str],
    title: str,
    reason: str,
) -> GitHubPullRequestResult:
    return GitHubPullRequestResult(
        branch=branch,
        body=body,
        changed_files=changed_files,
        fallback=True,
        metadata={"provider": "github", "fallback_reason": reason},
        pr_url=None,
        title=title,
    )


def _allowed_paths(*, config: GitHubConfig, bundle: dict[str, Any]) -> list[str]:
    raw = bundle.get("allowed_paths")
    if isinstance(raw, list) and raw:
        return [str(path) for path in raw]
    return list(config.allowed_paths)


def _validate_changed_files(diff: str, allowed_paths: list[str]) -> list[str]:
    changed_files = _changed_paths(diff)
    for path in changed_files:
        if not _path_inside(path, allowed_paths):
            raise ValueError(
                f"GitHub PR change touches path outside allowed_paths: "
                f"{path!r} not within {allowed_paths!r}"
            )
    return changed_files


def _new_files_from_diff(diff: str) -> dict[str, str]:
    files: dict[str, list[str]] = {}
    current_path: str | None = None
    source_was_dev_null = False

    for line in diff.splitlines():
        if line.startswith("--- "):
            source_was_dev_null = line.strip() == "--- /dev/null"
            current_path = None
            continue
        if line.startswith("+++ "):
            raw_path = line[len("+++ ") :].strip()
            if raw_path.startswith("b/"):
                raw_path = raw_path[2:]
            current_path = raw_path if source_was_dev_null else None
            if current_path:
                files[current_path] = []
            continue
        if current_path is None:
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("+") and not line.startswith("+++ "):
            files[current_path].append(line[1:])

    if not files and diff.strip():
        raise ValueError("GitHub PR creation currently supports new-file unified diffs")
    return {path: "\n".join(lines) + "\n" for path, lines in files.items()}


def _branch_name(config: GitHubConfig, incident: dict[str, Any]) -> str:
    incident_id = str(incident.get("id") or "incident")
    label = str(incident.get("label") or "fix")
    slug = "".join(char if char.isalnum() else "-" for char in label.lower()).strip("-")
    return f"{config.branch_prefix}/{incident_id}-{slug or 'fix'}"


def _pr_title(incident: dict[str, Any]) -> str:
    label = str(incident.get("label") or "agent failure")
    return f"Promptetheus fix: {label.replace('_', ' ')}"


def _pr_body(
    *,
    incident: dict[str, Any],
    bundle: dict[str, Any],
    fix_result: FixAgentResult,
) -> str:
    evidence_refs = ", ".join(str(ref) for ref in fix_result.evidence_refs) or "n/a"
    root_cause = bundle.get("root_cause") or "No root cause attached."
    regression = bundle.get("regression_case") or {}
    return "\n".join(
        [
            "## Promptetheus incident fix",
            "",
            f"- Incident: `{incident.get('id')}`",
            f"- Label: `{incident.get('label')}`",
            f"- Representative session: `{bundle.get('representative_session_id')}`",
            f"- Root cause: {root_cause}",
            f"- Evidence refs: {evidence_refs}",
            f"- Regression case: `{regression.get('id') or regression.get('note') or 'pending'}`",
            "",
            "## Plan",
            "",
            *[f"- {step}" for step in fix_result.plan],
            "",
            "## Verification",
            "",
            "Run the Promptetheus regression replay for this incident before merging.",
        ]
    )


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_app_jwt(config: GitHubConfig) -> str:
    # Tests can supply a fake private key. Real signing is lazy so ordinary local
    # dev and fallback paths do not require cryptography.
    if config.private_key == "test-private-key":
        return "test-github-app-jwt"
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "GitHub App JWT signing requires cryptography. Install server extras."
        ) from exc

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {"iat": now - 60, "exp": now + 540, "iss": config.app_id}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    private_key: Any = serialization.load_pem_private_key(
        str(config.private_key).encode("utf-8"),
        password=None,
    )
    signature = private_key.sign(
        signing_input.encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return signing_input + "." + _b64url(signature)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _private_key_from_env() -> str | None:
    raw = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    if not raw:
        return None
    if raw.startswith("base64:"):
        return base64.b64decode(raw[len("base64:") :]).decode("utf-8")
    return raw.replace("\\n", "\n")


def _json_list_env(name: str) -> list[str] | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(decoded, list):
        return [str(item) for item in decoded]
    return None


def _nested(value: dict[str, Any], path: list[str]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


__all__ = [
    "GitHubConfig",
    "GitHubPullRequestResult",
    "GitHubTransport",
    "create_pull_request",
    "github_fallback_forced",
    "github_pr_enabled",
]
