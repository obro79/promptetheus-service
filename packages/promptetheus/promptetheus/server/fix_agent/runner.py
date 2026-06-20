"""Fix-agent runner: redacted incident bundle + deterministic fallback fix.

State-0 has no live coding agent. FixAgentRunner.run produces a deterministic
fallback fix: a plan plus a well-formed unified diff that inserts a post-action
goal-verification guard into a file inside the connected repo's allowed paths. The
diff does not need to apply against a real repo here, but it must be parseable and
strictly confined to allowed_paths (per the Fix-Agent Security Contract).

build_incident_bundle assembles everything a fix agent needs to dispatch, with
secrets / cookies / auth headers / obvious PII redacted out of event payloads
before the bundle leaves the server.
"""

from __future__ import annotations

import re
from typing import Any

from promptetheus.server.models import FixAgentResult

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

#: Default repo paths a fallback fix is allowed to touch (Security Contract:
#: connected repos store allowed_paths_json; output outside them is rejected).
DEFAULT_ALLOWED_PATHS: tuple[str, ...] = ("agents/",)

#: How many events on each side of the critical step to include in the bundle.
_CONTEXT_WINDOW = 3

_REDACTED = "[REDACTED]"

# Substrings (case-insensitive) in a payload key that mark the value as sensitive.
_SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "secret",
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth_header",
    "cookie",
    "set-cookie",
    "session_token",
    "access_token",
    "refresh_token",
    "credential",
    "private_key",
    "ssn",
    "social_security",
    "credit_card",
    "card_number",
    "cvv",
)

# Value patterns that look like obvious PII / secrets regardless of their key.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+")
_CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _redact_text(text: str) -> str:
    """Mask obvious secrets / PII appearing inside a free-text value."""

    redacted = _BEARER_RE.sub(_REDACTED, text)
    redacted = _EMAIL_RE.sub(_REDACTED, redacted)
    redacted = _SSN_RE.sub(_REDACTED, redacted)
    redacted = _CREDIT_CARD_RE.sub(_REDACTED, redacted)
    return redacted


def _redact_value(value: Any, *, key_sensitive: bool) -> Any:
    """Recursively redact a payload value.

    A value is fully masked when its key is sensitive; otherwise text values are
    scrubbed for inline secrets/PII and containers are walked recursively.
    """

    if key_sensitive:
        return _REDACTED
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, key_sensitive=False) for item in value]
    return value


def _redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        out[key] = _redact_value(value, key_sensitive=_key_is_sensitive(str(key)))
    return out


def _redact_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of event with its payload + metadata redacted."""

    redacted = dict(event)
    payload = event.get("payload")
    if isinstance(payload, dict):
        redacted["payload"] = _redact_mapping(payload)
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        redacted["metadata"] = _redact_mapping(metadata)
    return redacted


# ---------------------------------------------------------------------------
# Incident bundle
# ---------------------------------------------------------------------------


def _events_around(
    events: list[dict[str, Any]], critical_seq: int | None
) -> list[dict[str, Any]]:
    """Select the events surrounding the critical step (inclusive window)."""

    if not events:
        return []
    if critical_seq is None:
        return list(events)

    index = next(
        (i for i, event in enumerate(events) if event.get("seq") == critical_seq),
        None,
    )
    if index is None:
        return list(events)

    start = max(0, index - _CONTEXT_WINDOW)
    end = min(len(events), index + _CONTEXT_WINDOW + 1)
    return events[start:end]


def build_incident_bundle(store: Any, incident: dict[str, Any]) -> dict[str, Any]:
    """Assemble a redacted dispatch bundle for incident.

    Contents: an incident summary, the representative session's user_goal, the
    redacted ordered events around the critical step, the analysis root cause, and
    the connected-repo allowed_paths. Secrets / cookies / auth headers / obvious
    PII are stripped from event payloads before returning.
    """

    representative_session_id = (
        incident.get("representative_session_id")
        or (incident.get("session_ids") or [None])[0]
    )

    session: dict[str, Any] | None = None
    if representative_session_id is not None:
        session = store.get_session(representative_session_id)
    user_goal = (session or {}).get("user_goal")

    critical_step_seq = incident.get("critical_step_seq")

    root_cause: str | None = None
    if representative_session_id is not None:
        analysis = store.get_analysis(representative_session_id)
        if analysis is not None:
            root_cause = analysis.get("root_cause")

    events: list[dict[str, Any]] = []
    if representative_session_id is not None:
        events = store.get_events(representative_session_id)
    windowed = _events_around(events, critical_step_seq)
    redacted_events = [_redact_event(event) for event in windowed]

    allowed_paths = _resolve_allowed_paths(incident)

    replay_artifact: dict[str, Any] | None = None
    signed_replay_url: str | None = None
    event_time_map: dict[str, Any] = {}
    if representative_session_id is not None:
        artifact = _replay_artifact(store, representative_session_id)
        if artifact is not None:
            replay_artifact = {
                "artifact_id": artifact.get("artifact_id"),
                "storage_path": artifact.get("storage_path"),
            }
            signed_replay_url = _signed_artifact_url(artifact)
            event_time_map = _event_time_map(events)

    regression_runs: list[dict[str, Any]] = []
    incident_id = incident.get("id")
    if incident_id is not None:
        regression_runs = store.list_regression_runs(incident_id)
    regression_case = regression_runs[-1] if regression_runs else {
        "stub": True,
        "incident_id": incident_id,
        "note": "State-0 regression case placeholder until live replay (P16/P17).",
    }

    connected_repo = connected_repo_stub(
        incident.get("project_id"), incident.get("allowed_paths")
    )

    redaction_summary = {
        "events_redacted": len(redacted_events),
        "fields_masked": _REDACTED,
        "policy": "server-side bundle redaction (secrets/cookies/auth/PII)",
    }

    source = _incident_source(incident, session)

    return {
        "incident": {
            "id": incident.get("id"),
            "workspace_id": incident.get("workspace_id"),
            "project_id": incident.get("project_id"),
            "label": incident.get("label"),
            "severity": incident.get("severity"),
            "status": incident.get("status"),
            "confidence": incident.get("confidence"),
            "session_count": len(incident.get("session_ids") or []),
        },
        "source": source,
        "representative_session_id": representative_session_id,
        "user_goal": user_goal,
        "critical_step_seq": critical_step_seq,
        "root_cause": root_cause,
        "events": redacted_events,
        "allowed_paths": list(allowed_paths),
        "replay_artifact": replay_artifact,
        "signed_replay_url": signed_replay_url,
        "event_time_map": event_time_map,
        "regression_case": regression_case,
        "connected_repo": connected_repo,
        "redaction_summary": redaction_summary,
    }


def _incident_source(
    incident: dict[str, Any], session: dict[str, Any] | None
) -> str:
    """Derive the agent's origin (browserbase / lambda / ...) for the heal loop.

    The source is an agnostic tag flowing end-to-end so the same remediation
    pipeline visibly heals incidents from any deployment. Resolution order:
    explicit incident.source, then the representative session's source or its
    metadata.source, else "unknown".
    """

    raw = incident.get("source")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(session, dict):
        candidate = session.get("source")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        metadata = session.get("metadata")
        if isinstance(metadata, dict):
            meta_source = metadata.get("source")
            if isinstance(meta_source, str) and meta_source.strip():
                return meta_source.strip()
    return "unknown"


def _resolve_allowed_paths(source: dict[str, Any]) -> tuple[str, ...]:
    """Pull a connected-repo allowed-paths list from an incident/bundle, else default."""

    raw = source.get("allowed_paths")
    if isinstance(raw, (list, tuple)) and raw:
        return tuple(str(path) for path in raw)
    return DEFAULT_ALLOWED_PATHS


# ---------------------------------------------------------------------------
# Incident context (agent surface)
# ---------------------------------------------------------------------------

#: Content types that mark an artifact as a replay recording.
_REPLAY_CONTENT_TYPES: frozenset[str] = frozenset({"video/webm"})


def connected_repo_stub(
    project_id: str | None, allowed_paths: Any = None
) -> dict[str, Any]:
    """Return a connected-repo descriptor for project_id.

    State-0 has no connected-repo entity; this is an explicit stub deriving
    allowed_paths from the supplied list (e.g. an incident's allowed_paths) or
    the fix-agent default. repo is left None until a real GitHub link exists.
    """

    paths = _resolve_allowed_paths({"allowed_paths": allowed_paths})
    return {
        "project_id": project_id,
        "repo": None,
        "allowed_paths": list(paths),
        "stub": True,
    }


def _session_artifacts(store: Any, session_id: str | None) -> list[dict[str, Any]]:
    """Best-effort list of a session's artifact rows.

    The frozen Store protocol exposes only get_artifact(id); a real
    SupabaseStore is expected to grow list_artifacts(session_id), and the
    InMemoryStore keeps rows in a private map. Try both, tolerantly, so this
    keeps working today and forward-compatibly. Never raises.
    """

    if session_id is None:
        return []
    lister = getattr(store, "list_artifacts", None)
    if callable(lister):
        try:
            return [dict(row) for row in lister(session_id)]
        except Exception:  # pragma: no cover - defensive
            pass
    raw = getattr(store, "_artifacts", None)
    if isinstance(raw, dict):
        return [
            dict(row)
            for row in raw.values()
            if isinstance(row, dict) and row.get("session_id") == session_id
        ]
    return []


def _replay_artifact(store: Any, session_id: str | None) -> dict[str, Any] | None:
    """Pick the session's replay artifact (a video recording), else any artifact."""

    artifacts = _session_artifacts(store, session_id)
    if not artifacts:
        return None
    for artifact in artifacts:
        if artifact.get("artifact_type") == "replay" or (
            str(artifact.get("content_type") or "") in _REPLAY_CONTENT_TYPES
        ):
            return artifact
    return artifacts[0]


def _signed_artifact_url(artifact: dict[str, Any]) -> str:
    """Synthetic short-lived artifact URL mirroring GET /artifacts/{id}."""

    storage_path = artifact.get("storage_path") or ""
    return f"https://artifacts.local/signed/{storage_path}?token=dev"


def _event_time_map(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Map each event seq -> its timestamp so a replay can sync to the timeline."""

    time_map: dict[str, Any] = {}
    for event in events:
        seq = event.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            time_map[str(seq)] = event.get("timestamp")
    return time_map


def build_incident_context(store: Any, incident: dict[str, Any]) -> dict[str, Any]:
    """Assemble the agent-facing context bundle for incident.

    Extends build_incident_bundle (which performs server-side redaction) with the
    extra slices the MCP read tools project: detector labels + evidence chips, the
    replay artifact's signed URL and per-seq event_time_map, the latest regression
    case, and the connected-repo stub. Redaction stays in build_incident_bundle —
    no new raw event payloads are introduced here.
    """

    bundle = build_incident_bundle(store, incident)
    representative_session_id = bundle.get("representative_session_id")

    labels: list[str] = []
    evidence: list[dict[str, Any]] = []
    if representative_session_id is not None:
        analysis = store.get_analysis(representative_session_id)
        if analysis is not None:
            labels = [str(label) for label in (analysis.get("labels") or [])]
            for detection in analysis.get("detections") or []:
                if isinstance(detection, dict):
                    evidence.append(
                        {
                            "label": detection.get("label"),
                            "confidence": detection.get("confidence"),
                            "evidence_refs": detection.get("evidence_refs"),
                            "critical_step_seq": detection.get("critical_step_seq"),
                        }
                    )

    events: list[dict[str, Any]] = []
    if representative_session_id is not None:
        events = store.get_events(representative_session_id)
    artifact = _replay_artifact(store, representative_session_id)
    replay = {
        "artifact_id": artifact.get("artifact_id") if artifact else None,
        "signed_url": _signed_artifact_url(artifact) if artifact else None,
        "expires_in": 300 if artifact else None,
        "event_time_map": _event_time_map(events),
    }

    regression_runs: list[dict[str, Any]] = []
    incident_id = incident.get("id")
    if incident_id is not None:
        regression_runs = store.list_regression_runs(incident_id)
    regression_case = regression_runs[-1] if regression_runs else None

    connected_repo = connected_repo_stub(
        incident.get("project_id"), incident.get("allowed_paths")
    )

    return {
        **bundle,
        "labels": labels,
        "evidence": evidence,
        "replay": replay,
        "regression_case": regression_case,
        "connected_repo": connected_repo,
    }


# ---------------------------------------------------------------------------
# Fallback fix runner
# ---------------------------------------------------------------------------


def _short_label(label: str | None) -> str:
    """Derive a branch-safe short label from an incident label."""

    if not label:
        return "fix"
    slug = re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")
    return slug or "fix"


def _path_inside(path: str, allowed_paths: list[str]) -> bool:
    """True when path falls under any allowed prefix.

    A trailing-slash prefix (agents/) matches anything beneath the directory;
    a bare prefix also matches the exact file. .. segments are never allowed.
    """

    normalized = path.lstrip("/")
    if ".." in normalized.split("/"):
        return False
    for prefix in allowed_paths:
        clean = str(prefix).lstrip("/")
        if clean.endswith("/"):
            if normalized.startswith(clean):
                return True
        elif normalized == clean or normalized.startswith(clean + "/"):
            return True
    return False


def _guard_target_path(allowed_paths: list[str]) -> str:
    """Choose a concrete file path inside allowed_paths for the guard insert."""

    first = str(allowed_paths[0]).lstrip("/")
    base = first if first.endswith("/") else first + "/"
    return f"{base}goal_verification_guard.py"


def _build_guard_diff(target_path: str, incident_id: str, label: str | None) -> str:
    """Render a well-formed unified diff adding a post-action goal-verification guard."""

    constraint = label or "the user goal"
    added_lines = [
        '"""Post-action goal-verification guard (generated by Promptetheus).',
        "",
        f"Guards against regressions of incident {incident_id} ({constraint}).",
        "Run this after the agent claims completion to confirm the goal actually held.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "",
        "def verify_goal_satisfied(goal_check: dict, agent_claimed_success: bool) -> None:",
        '    """Fail loudly when the agent claims success but the goal check did not pass."""',
        "",
        '    passed = bool(goal_check.get("passed"))',
        "    if agent_claimed_success and not passed:",
        '        mismatches = goal_check.get("mismatches") or []',
        "        raise AssertionError(",
        f'            f"goal not satisfied for {constraint}: {{mismatches}}"',
        "        )",
    ]

    hunk_body = "\n".join(f"+{line}" for line in added_lines)
    count = len(added_lines)
    return f"--- /dev/null\n+++ b/{target_path}\n@@ -0,0 +1,{count} @@\n{hunk_body}\n"


def _changed_paths(diff: str) -> list[str]:
    """Extract the destination paths a unified diff touches (+++ b/... lines)."""

    paths: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[len("+++ ") :].strip()
            if target in ("/dev/null", ""):
                continue
            if target.startswith("b/"):
                target = target[2:]
            paths.append(target)
    return paths


class FixAgentRunner:
    """Deterministic State-0 fix agent.

    A real agent slots in behind this same interface later. run always returns
    a fallback fix (metadata["fallback"] is True) whose diff is confined to the
    runner's allowed_paths.
    """

    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        self.allowed_paths: list[str] = (
            list(allowed_paths) if allowed_paths else list(DEFAULT_ALLOWED_PATHS)
        )

    def run(self, incident_bundle: dict[str, Any]) -> FixAgentResult:
        """Produce a fallback plan + unified diff confined to allowed_paths.

        The runner's allowed_paths is the authoritative security boundary. The
        bundle may *request* where the guard lands via its own allowed_paths;
        that request must itself fall inside the runner's allow-list. Any generated
        change that would touch a path outside the runner's allowed_paths raises
        ValueError (Fix-Agent Security Contract).
        """

        incident = incident_bundle.get("incident") or {}
        incident_id = str(incident.get("id") or "incident")
        label = incident.get("label")
        root_cause = incident_bundle.get("root_cause")
        user_goal = incident_bundle.get("user_goal")

        target_path = self._guard_target(incident_bundle)
        diff = _build_guard_diff(target_path, incident_id, label)

        # Security Contract: the runner's allow-list is the hard boundary. Reject
        # any generated change that escapes it (path traversal, requested path
        # outside the connected-repo allow-list, etc.).
        for changed in _changed_paths(diff):
            if not _path_inside(changed, self.allowed_paths):
                raise ValueError(
                    "fix-agent change touches path outside allowed_paths: "
                    f"{changed!r} not within {self.allowed_paths!r}"
                )

        plan = self._build_plan(label, user_goal, root_cause, target_path)
        metadata = {
            "fallback": True,
            "branch": f"promptetheus/{incident_id}-{_short_label(label)}",
            "allowed_paths": list(self.allowed_paths),
        }
        changed_files = _changed_paths(diff)
        return FixAgentResult(
            plan=plan,
            diff=diff,
            metadata=metadata,
            summary="Deterministic fallback fix with goal-verification guard.",
            changed_files=changed_files,
            runner="deterministic",
            confidence=float(incident.get("confidence") or 0.0),
            evidence_refs=[
                int(event.get("seq"))
                for event in incident_bundle.get("events") or []
                if isinstance(event.get("seq"), int) and not isinstance(event.get("seq"), bool)
            ],
            fallback=True,
        )

    def _guard_target(self, incident_bundle: dict[str, Any]) -> str:
        """Pick the guard file path the bundle requests, else the runner default.

        The path is *not* clamped here on purpose: if the bundle asks for a path
        outside the runner's allow-list, run lets the security check reject it
        rather than silently rewriting the request.
        """

        bundle_paths = incident_bundle.get("allowed_paths")
        if isinstance(bundle_paths, (list, tuple)) and bundle_paths:
            return _guard_target_path([str(path) for path in bundle_paths])
        return _guard_target_path(self.allowed_paths)

    @staticmethod
    def _build_plan(
        label: str | None,
        user_goal: str | None,
        root_cause: str | None,
        target_path: str,
    ) -> list[str]:
        goal_text = user_goal or "the stated user goal"
        cause_text = root_cause or f"the detected {label or 'failure'}"
        return [
            f"Reproduce the failure: {cause_text}.",
            f"Add a post-action goal-verification guard at {target_path}.",
            f"Assert the agent re-checks {goal_text!r} before claiming success.",
            "Wire the guard into the agent's completion path so a failed check blocks the success claim.",
            "Open a PR on a promptetheus/ branch and run the regression replay to confirm the fix.",
        ]


__all__ = [
    "DEFAULT_ALLOWED_PATHS",
    "FixAgentRunner",
    "build_incident_bundle",
    "build_incident_context",
    "connected_repo_stub",
]
