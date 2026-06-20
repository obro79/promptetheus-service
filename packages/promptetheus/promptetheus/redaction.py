"""Default redactors for Promptetheus events.

A redactor is a callable (event) -> event compatible with the redact hook
on Session: it receives the fully-stamped event
envelope and returns a scrubbed copy (the Session swaps in whatever it returns).

build_default_redactor returns a dependency-free, regex-based redactor
that scrubs common secrets and PII (API keys, bearer tokens, AWS keys, emails,
card-like numbers) from the event's payload and metadata — never the
envelope identity fields (type/session_id/seq/timestamp/
idempotency_key), which the server relies on. It also blanks values whose key
name looks sensitive (password, api_key, authorization, ...).

Redaction runs in-process before an event is handed to the transport, so raw
secrets never leave the agent. It is best-effort and never raises: on any error
the original event is returned unchanged (failing open on availability, not on
secrecy — so pair it with not logging secrets elsewhere).
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Callable, Mapping, MutableMapping

logger = logging.getLogger("promptetheus")

REDACTION_PLACEHOLDER = "[REDACTED]"

# Envelope fields that must never be altered (the server keys on them).
_PROTECTED_ENVELOPE_KEYS = frozenset(
    {"type", "session_id", "seq", "timestamp", "idempotency_key"}
)

# Dict keys whose *value* is replaced wholesale, regardless of content.
_SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "api-key",
    "authorization",
    "auth_token",
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
    "session_key",
    "credential",
)

# (name, compiled pattern) applied to string values. Order matters only for
# readability; matches are independent. Each replaces the matched span with the
# placeholder.
_DEFAULT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # OpenAI / Anthropic style secret keys (sk-..., sk-ant-...).
    ("provider_api_key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{16,}\b")),
    # Bearer tokens in auth header strings.
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)),
    # AWS access key IDs.
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # GitHub tokens.
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    # Generic JWTs.
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")),
    # Email addresses.
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # Card-like 13-16 digit runs (allowing spaces/dashes between groups).
    ("card_number", re.compile(r"\b(?:\d[ \-]?){13,16}\b")),
)


def _key_is_sensitive_with(key: Any, sensitive_keys: tuple[str, ...]) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(token in lowered for token in sensitive_keys)


def _hash_value(raw: str) -> str:
    """A stable, non-reversible token for a redacted value (sha256, truncated).

    Lets equal secrets correlate across events without exposing the value.
    """
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _scrub_string(
    value: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    replace: Callable[[str], str],
) -> str:
    for _name, pattern in patterns:
        value = pattern.sub(lambda m: replace(m.group(0)), value)
    return value


def _scrub(
    value: Any,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    sensitive_keys: tuple[str, ...],
    allow_keys: frozenset[str],
    replace: Callable[[str], str],
) -> Any:
    """Recursively scrub a value (dict/list/str), returning a scrubbed copy."""

    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in allow_keys:
                out[key] = item
            elif _key_is_sensitive_with(key, sensitive_keys):
                out[key] = replace(str(item))
            else:
                out[key] = _scrub(item, patterns, sensitive_keys, allow_keys, replace)
        return out
    if isinstance(value, (list, tuple)):
        scrubbed = [
            _scrub(item, patterns, sensitive_keys, allow_keys, replace)
            for item in value
        ]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
    if isinstance(value, str):
        return _scrub_string(value, patterns, replace)
    return value


def build_default_redactor(
    *,
    extra_patterns: list[tuple[str, str]] | None = None,
    extra_sensitive_keys: list[str] | None = None,
    allow_keys: list[str] | None = None,
    hash_values: bool = False,
) -> Callable[[MutableMapping[str, Any]], dict[str, Any]]:
    """Build a redactor that scrubs common secrets/PII from event payloads.

    Args:
        extra_patterns: additional (name, regex) pairs whose matches are
            replaced, on top of the built-in patterns.
        extra_sensitive_keys: additional dict-key substrings whose values are
            replaced wholesale.
        allow_keys: dict-key names (case-insensitive, exact match) that are an
            allowlist: their values are never redacted, even if they match a
            sensitive substring or pattern. Use for fields you know are safe.
        hash_values: when True, redacted values are replaced with a stable
            sha256-prefixed token instead of the fixed placeholder, so equal
            secrets correlate across events without exposing the raw value.

    Returns:
        A callable (event) -> event that returns a scrubbed copy of the
        event. The envelope identity fields are left untouched; payload and
        metadata are deep-scrubbed. Never raises — on error it returns the
        event unchanged.
    """

    patterns: tuple[tuple[str, re.Pattern[str]], ...] = _DEFAULT_PATTERNS
    if extra_patterns:
        compiled_extra = tuple((name, re.compile(rx)) for name, rx in extra_patterns)
        patterns = patterns + compiled_extra

    sensitive_keys: tuple[str, ...] = _SENSITIVE_KEY_SUBSTRINGS
    if extra_sensitive_keys:
        sensitive_keys = sensitive_keys + tuple(k.lower() for k in extra_sensitive_keys)

    allowed: frozenset[str] = frozenset(k.lower() for k in (allow_keys or ()))
    replace: Callable[[str], str] = (
        _hash_value if hash_values else (lambda _raw: REDACTION_PLACEHOLDER)
    )

    def _redactor(event: MutableMapping[str, Any]) -> dict[str, Any]:
        try:
            scrubbed: dict[str, Any] = {}
            for key, value in event.items():
                if key in _PROTECTED_ENVELOPE_KEYS:
                    scrubbed[key] = value
                elif isinstance(key, str) and key.lower() in allowed:
                    scrubbed[key] = value
                elif _key_is_sensitive_with(key, sensitive_keys):
                    scrubbed[key] = replace(str(value))
                else:
                    scrubbed[key] = _scrub(
                        value, patterns, sensitive_keys, allowed, replace
                    )
            return scrubbed
        except Exception:  # pragma: no cover - redaction must never crash telemetry
            logger.exception(
                "Promptetheus default redactor failed; passing event through"
            )
            return dict(event)

    return _redactor


__all__ = ["REDACTION_PLACEHOLDER", "build_default_redactor"]
