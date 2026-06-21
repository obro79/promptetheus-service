"""Short-lived agent runtime guidance storage.

Runtime state helps an agent while a trace is active: recent working memory,
tool-call dedupe, live heartbeat state, and hints. It is intentionally not
canonical product storage. Durable state still flows through the Store/Supabase
path; this module may forget state at any time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from promptetheus.redaction import build_default_redactor

logger = logging.getLogger("promptetheus")

DEFAULT_RUNTIME_TTL_SECONDS = 24 * 60 * 60
DEFAULT_HEARTBEAT_TTL_SECONDS = 15 * 60
DEFAULT_FINALIZED_TTL_SECONDS = 15 * 60
_MAX_MEMORY_ENTRIES = 200
_FAILED_STATUSES = frozenset({"failed", "failure", "error", "errored"})
_SUCCESS_STATUSES = frozenset({"success", "succeeded", "passed", "complete", "completed"})


@dataclass(frozen=True)
class RuntimeScope:
    workspace_id: str
    project_id: str | None
    session_id: str


class RuntimeStore(Protocol):
    """Best-effort runtime state backend."""

    def add_memory(
        self,
        scope: RuntimeScope,
        entry: dict[str, Any],
    ) -> dict[str, Any]: ...

    def list_memory(self, scope: RuntimeScope, *, limit: int = 20) -> list[dict[str, Any]]: ...

    def record_tool_call(
        self,
        scope: RuntimeScope,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def set_heartbeat(
        self,
        scope: RuntimeScope,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def next_hint(self, scope: RuntimeScope) -> Any | None: ...

    def finalize_session(self, scope: RuntimeScope) -> dict[str, Any]: ...


def runtime_from_env() -> RuntimeStore:
    """Return the configured runtime backend.

    Defaults to Redis when a Redis URL exists, otherwise in-memory. Missing Redis
    support falls back to memory because runtime state is non-canonical.
    """

    mode = os.environ.get("PROMPTETHEUS_RUNTIME", "").strip().lower()
    if mode == "off":
        return NoopRuntimeStore()
    if mode == "memory":
        return InMemoryRuntimeStore()

    redis_url = os.environ.get("PROMPTETHEUS_REDIS_URL") or os.environ.get("REDIS_URL")
    if mode == "redis" or (mode != "memory" and redis_url):
        if not redis_url:
            logger.warning("PROMPTETHEUS_RUNTIME=redis set without REDIS_URL; using memory runtime")
            return InMemoryRuntimeStore()
        try:
            return RedisRuntimeStore(redis_url)
        except RuntimeError:
            logger.warning("Redis runtime unavailable; using memory runtime", exc_info=True)
            return InMemoryRuntimeStore()
    return InMemoryRuntimeStore()


def runtime_ttl_seconds() -> int:
    return _positive_int_env("PROMPTETHEUS_RUNTIME_TTL_SECONDS", DEFAULT_RUNTIME_TTL_SECONDS)


def _heartbeat_ttl_seconds() -> int:
    return _positive_int_env("PROMPTETHEUS_RUNTIME_HEARTBEAT_TTL_SECONDS", DEFAULT_HEARTBEAT_TTL_SECONDS)


def _finalized_ttl_seconds() -> int:
    return _positive_int_env("PROMPTETHEUS_RUNTIME_FINALIZED_TTL_SECONDS", DEFAULT_FINALIZED_TTL_SECONDS)


def canonical_tool_fingerprint(payload: dict[str, Any]) -> str:
    canonical = {
        "tool_name": str(payload.get("tool_name") or ""),
        "command": str(payload.get("command") or ""),
        "args": payload.get("args") if isinstance(payload.get("args"), dict) else {},
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class NoopRuntimeStore:
    """Disabled runtime store."""

    def add_memory(self, scope: RuntimeScope, entry: dict[str, Any]) -> dict[str, Any]:
        return {}

    def list_memory(self, scope: RuntimeScope, *, limit: int = 20) -> list[dict[str, Any]]:
        return []

    def record_tool_call(self, scope: RuntimeScope, payload: dict[str, Any]) -> dict[str, Any]:
        return {"seen_recently": False, "attempt_count": 0, "failure_count": 0, "hint": None}

    def set_heartbeat(self, scope: RuntimeScope, payload: dict[str, Any]) -> dict[str, Any]:
        return {}

    def next_hint(self, scope: RuntimeScope) -> Any | None:
        return None

    def finalize_session(self, scope: RuntimeScope) -> dict[str, Any]:
        return {
            "memory_count": 0,
            "tool_fingerprint_count": 0,
            "failed_tool_fingerprint_count": 0,
            "heartbeat_present": False,
            "disabled": True,
        }


class InMemoryRuntimeStore:
    """Thread-safe runtime store for tests and local dev."""

    def __init__(
        self,
        *,
        ttl_seconds: int | None = None,
        heartbeat_ttl_seconds: int | None = None,
        finalized_ttl_seconds: int | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else runtime_ttl_seconds()
        self._heartbeat_ttl_seconds = (
            heartbeat_ttl_seconds
            if heartbeat_ttl_seconds is not None
            else _heartbeat_ttl_seconds()
        )
        self._finalized_ttl_seconds = (
            finalized_ttl_seconds
            if finalized_ttl_seconds is not None
            else _finalized_ttl_seconds()
        )
        self._lock = threading.RLock()
        self._memory: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self._attempts: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
        self._heartbeats: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._expires_at: dict[tuple[str, str, str], float] = {}
        self._heartbeat_expires_at: dict[tuple[str, str, str], float] = {}

    def add_memory(self, scope: RuntimeScope, entry: dict[str, Any]) -> dict[str, Any]:
        key = _scope_key(scope)
        stored = {
            "kind": str(entry.get("kind") or "note"),
            "value": _redact_value(entry.get("value")),
            "metadata": _redact_value(_dict_or_empty(entry.get("metadata"))),
            "created_at": _now_iso(),
        }
        with self._lock:
            self._cleanup_locked(key)
            rows = self._memory.setdefault(key, [])
            rows.append(stored)
            if len(rows) > _MAX_MEMORY_ENTRIES:
                del rows[: len(rows) - _MAX_MEMORY_ENTRIES]
            self._touch_locked(key, self._ttl_seconds)
        return dict(stored)

    def list_memory(self, scope: RuntimeScope, *, limit: int = 20) -> list[dict[str, Any]]:
        key = _scope_key(scope)
        safe_limit = _safe_limit(limit)
        with self._lock:
            self._cleanup_locked(key)
            rows = self._memory.get(key, [])
            return [dict(row) for row in rows[-safe_limit:]]

    def record_tool_call(self, scope: RuntimeScope, payload: dict[str, Any]) -> dict[str, Any]:
        key = _scope_key(scope)
        fingerprint = canonical_tool_fingerprint(payload)
        status = _normalized_status(payload.get("status"))
        with self._lock:
            self._cleanup_locked(key)
            attempts = self._attempts.setdefault(key, {})
            existing = attempts.get(fingerprint, _new_tool_stats(fingerprint, payload))
            prior_failures = int(existing.get("failure_count") or 0)
            if status in _FAILED_STATUSES:
                existing["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
                existing["failure_count"] = prior_failures + 1
                existing["last_error"] = str(payload.get("error") or "")
            elif status in _SUCCESS_STATUSES:
                existing["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
                existing["success_count"] = int(existing.get("success_count") or 0) + 1
                existing["last_error"] = None
            existing["last_status"] = status
            existing["last_seen_at"] = _now_iso()
            attempts[fingerprint] = existing
            self._touch_locked(key, self._ttl_seconds)
            return _tool_response(existing, seen_recently=prior_failures > 0)

    def set_heartbeat(self, scope: RuntimeScope, payload: dict[str, Any]) -> dict[str, Any]:
        key = _scope_key(scope)
        stored = _redact_value(dict(payload))
        stored["updated_at"] = _now_iso()
        with self._lock:
            self._cleanup_locked(key)
            self._heartbeats[key] = stored
            self._touch_heartbeat_locked(key, self._heartbeat_ttl_seconds)
        return dict(stored)

    def next_hint(self, scope: RuntimeScope) -> Any | None:
        key = _scope_key(scope)
        with self._lock:
            self._cleanup_locked(key)
            for stats in self._attempts.get(key, {}).values():
                if int(stats.get("failure_count") or 0) > 0:
                    return _hint_for(stats)
        return None

    def finalize_session(self, scope: RuntimeScope) -> dict[str, Any]:
        key = _scope_key(scope)
        with self._lock:
            self._cleanup_locked(key)
            summary = _summary(
                self._memory.get(key, []),
                self._attempts.get(key, {}),
                self._heartbeats.get(key),
            )
            self._touch_locked(key, self._finalized_ttl_seconds)
            self._touch_heartbeat_locked(key, self._finalized_ttl_seconds)
            return summary

    def _touch_locked(self, key: tuple[str, str, str], ttl_seconds: int) -> None:
        self._expires_at[key] = time.time() + max(1, ttl_seconds)

    def _touch_heartbeat_locked(
        self, key: tuple[str, str, str], ttl_seconds: int
    ) -> None:
        self._heartbeat_expires_at[key] = time.time() + max(1, ttl_seconds)

    def _cleanup_locked(self, key: tuple[str, str, str]) -> None:
        now = time.time()
        expires_at = self._expires_at.get(key)
        if expires_at is not None and expires_at <= now:
            self._memory.pop(key, None)
            self._attempts.pop(key, None)
            self._expires_at.pop(key, None)
        heartbeat_expires_at = self._heartbeat_expires_at.get(key)
        if heartbeat_expires_at is not None and heartbeat_expires_at <= now:
            self._heartbeats.pop(key, None)
            self._heartbeat_expires_at.pop(key, None)


class RedisRuntimeStore:
    """Redis-backed runtime store.

    Uses redis-py synchronously because runtime endpoints are lightweight and
    best-effort. Any Redis operation failure returns a safe fallback.
    """

    def __init__(self, redis_url: str, *, prefix: str = "pt:v1") -> None:
        try:
            import redis  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("RedisRuntimeStore requires redis>=5") from exc
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix

    def add_memory(self, scope: RuntimeScope, entry: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "kind": str(entry.get("kind") or "note"),
            "value": _redact_value(entry.get("value")),
            "metadata": _redact_value(_dict_or_empty(entry.get("metadata"))),
            "created_at": _now_iso(),
        }
        try:
            key = self._key(scope, "memory")
            self._redis.rpush(key, json.dumps(stored, default=str))
            self._redis.ltrim(key, -_MAX_MEMORY_ENTRIES, -1)
            self._expire_runtime_scope(scope, runtime_ttl_seconds())
        except Exception:
            logger.debug("Promptetheus Redis runtime memory write failed", exc_info=True)
        return dict(stored)

    def list_memory(self, scope: RuntimeScope, *, limit: int = 20) -> list[dict[str, Any]]:
        try:
            rows = self._redis.lrange(self._key(scope, "memory"), -_safe_limit(limit), -1)
            parsed = [_json_dict(raw) for raw in rows]
            return [row for row in parsed if row]
        except Exception:
            logger.debug("Promptetheus Redis runtime memory read failed", exc_info=True)
            return []

    def record_tool_call(self, scope: RuntimeScope, payload: dict[str, Any]) -> dict[str, Any]:
        fingerprint = canonical_tool_fingerprint(payload)
        try:
            key = self._key(scope, "attempts")
            existing = _json_dict(self._redis.hget(key, fingerprint)) or _new_tool_stats(
                fingerprint, payload
            )
            prior_failures = int(existing.get("failure_count") or 0)
            status = _normalized_status(payload.get("status"))
            if status in _FAILED_STATUSES:
                existing["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
                existing["failure_count"] = prior_failures + 1
                existing["last_error"] = str(payload.get("error") or "")
            elif status in _SUCCESS_STATUSES:
                existing["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
                existing["success_count"] = int(existing.get("success_count") or 0) + 1
                existing["last_error"] = None
            existing["last_status"] = status
            existing["last_seen_at"] = _now_iso()
            self._redis.hset(key, fingerprint, json.dumps(existing, default=str))
            self._expire_runtime_scope(scope, runtime_ttl_seconds())
            return _tool_response(existing, seen_recently=prior_failures > 0)
        except Exception:
            logger.debug("Promptetheus Redis runtime tool call failed", exc_info=True)
            return {"seen_recently": False, "attempt_count": 0, "failure_count": 0, "hint": None}

    def set_heartbeat(self, scope: RuntimeScope, payload: dict[str, Any]) -> dict[str, Any]:
        stored = _redact_value(dict(payload))
        stored["updated_at"] = _now_iso()
        try:
            self._redis.setex(
                self._key(scope, "heartbeat"),
                _heartbeat_ttl_seconds(),
                json.dumps(stored, default=str),
            )
        except Exception:
            logger.debug("Promptetheus Redis runtime heartbeat failed", exc_info=True)
        return dict(stored)

    def next_hint(self, scope: RuntimeScope) -> Any | None:
        try:
            for raw in self._redis.hvals(self._key(scope, "attempts")):
                stats = _json_dict(raw)
                if int(stats.get("failure_count") or 0) > 0:
                    return _hint_for(stats)
        except Exception:
            logger.debug("Promptetheus Redis runtime hint failed", exc_info=True)
        return None

    def finalize_session(self, scope: RuntimeScope) -> dict[str, Any]:
        try:
            memory = self.list_memory(scope, limit=_MAX_MEMORY_ENTRIES)
            attempts = {
                str(stats.get("fingerprint") or index): stats
                for index, stats in enumerate(
                    _json_dict(raw)
                    for raw in self._redis.hvals(self._key(scope, "attempts"))
                )
                if stats
            }
            heartbeat = _json_dict(self._redis.get(self._key(scope, "heartbeat")))
            summary = _summary(memory, attempts, heartbeat)
            self._expire_all_scope(scope, _finalized_ttl_seconds())
            return summary
        except Exception:
            logger.debug("Promptetheus Redis runtime finalize failed", exc_info=True)
            return {
                "memory_count": 0,
                "tool_fingerprint_count": 0,
                "failed_tool_fingerprint_count": 0,
                "heartbeat_present": False,
            }

    def _key(self, scope: RuntimeScope, leaf: str) -> str:
        project_id = scope.project_id or "-"
        return (
            f"{self._prefix}:{_safe_key(scope.workspace_id)}:{_safe_key(project_id)}:"
            f"session:{_safe_key(scope.session_id)}:{leaf}"
        )

    def _expire_runtime_scope(self, scope: RuntimeScope, ttl_seconds: int) -> None:
        ttl = max(1, ttl_seconds)
        for leaf in ("memory", "attempts"):
            self._redis.expire(self._key(scope, leaf), ttl)

    def _expire_all_scope(self, scope: RuntimeScope, ttl_seconds: int) -> None:
        ttl = max(1, ttl_seconds)
        for leaf in ("memory", "attempts", "heartbeat"):
            self._redis.expire(self._key(scope, leaf), ttl)


def _scope_key(scope: RuntimeScope) -> tuple[str, str, str]:
    return (scope.workspace_id, scope.project_id or "-", scope.session_id)


def _safe_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _safe_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        return 20
    return max(1, min(limit, _MAX_MEMORY_ENTRIES))


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalized_status(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower() or None


def _new_tool_stats(fingerprint: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "fingerprint": fingerprint,
        "tool_name": str(payload.get("tool_name") or ""),
        "command": str(payload.get("command") or ""),
        "args": _redact_value(_dict_or_empty(payload.get("args"))),
        "attempt_count": 0,
        "failure_count": 0,
        "success_count": 0,
        "last_status": None,
        "last_error": None,
        "last_seen_at": None,
    }


def _tool_response(stats: dict[str, Any], *, seen_recently: bool) -> dict[str, Any]:
    return {
        "seen_recently": seen_recently,
        "attempt_count": int(stats.get("attempt_count") or 0),
        "failure_count": int(stats.get("failure_count") or 0),
        "fingerprint": stats.get("fingerprint"),
        "hint": _hint_for(stats) if seen_recently else None,
    }


def _hint_for(stats: dict[str, Any]) -> dict[str, Any]:
    tool_name = stats.get("tool_name") or "this tool"
    failure_count = int(stats.get("failure_count") or 0)
    command = stats.get("command")
    message = (
        f"{tool_name} has failed {failure_count} time(s) for this same input. "
        "Change hypothesis before retrying."
    )
    if command:
        message = (
            f"{tool_name} command {command!r} has failed {failure_count} time(s). "
            "Change hypothesis before retrying."
        )
    return {
        "kind": "repeated_tool_failure",
        "message": message,
        "tool_name": tool_name,
        "command": command,
        "failure_count": failure_count,
    }


def _summary(
    memory: list[dict[str, Any]],
    attempts: dict[str, dict[str, Any]],
    heartbeat: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "memory_count": len(memory),
        "tool_fingerprint_count": len(attempts),
        "failed_tool_fingerprint_count": sum(
            1 for stats in attempts.values() if int(stats.get("failure_count") or 0) > 0
        ),
        "heartbeat_present": heartbeat is not None,
    }


def _redact_value(value: Any) -> Any:
    redactor = build_default_redactor()
    event = {
        "type": "state_change",
        "session_id": "runtime",
        "timestamp": "1970-01-01T00:00:00Z",
        "seq": 0,
        "idempotency_key": "runtime:redact:0",
        "payload": {"value": value},
    }
    try:
        redacted = redactor(event)
    except Exception:
        return value
    payload = redacted.get("payload", {}) if isinstance(redacted, dict) else {}
    return payload.get("value") if isinstance(payload, dict) else value


def _json_dict(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


__all__ = [
    "InMemoryRuntimeStore",
    "NoopRuntimeStore",
    "RedisRuntimeStore",
    "RuntimeScope",
    "RuntimeStore",
    "canonical_tool_fingerprint",
    "runtime_from_env",
]
