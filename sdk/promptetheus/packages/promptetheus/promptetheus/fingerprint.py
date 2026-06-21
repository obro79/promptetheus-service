"""Failure fingerprinting: turn a failed session into a stable signature.

Tail sampling keeps the sessions that failed; this groups them. A fingerprint is
a short, deterministic hash of the normalized failure signals in a session (the
error kind, the failing tool, the goal mismatch), so two runs that failed the
same way share a fingerprint and can be clustered, while runs that failed
differently do not.

This is a pure function of a session's events. It performs no I/O and never
raises, so it is safe to call from a user's test suite, from the CLI, or
server-side when clustering incidents. It deliberately does not itself cluster or
store anything: it only computes the signature.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# Patterns that turn a specific error message into a stable shape, so that
# "timeout after 3133ms" and "timeout after 9120ms" collapse to one fingerprint.
_HEX_OR_UUID = re.compile(r"\b[0-9a-fA-F]{8,}\b")
# Numbers are normalized even when glued to a unit suffix (3133ms), so a varying
# count never changes the fingerprint.
_NUMBER = re.compile(r"\d+")
_QUOTED = re.compile(r"(['\"]).*?\1")
_WHITESPACE = re.compile(r"\s+")
_PATHLIKE = re.compile(r"(/[\w.\-]+)+")
_AT_HEX = re.compile(r"0x[0-9a-fA-F]+")


def _normalize_message(message: str) -> str:
    """Collapse a specific error string to a stable, comparable shape.

    Strips the parts that vary run to run (numbers, hex/uuids, quoted literals,
    file paths, memory addresses) so that the same class of error normalizes to
    the same text. Lowercased and whitespace-collapsed.
    """

    text = message.strip()
    text = _AT_HEX.sub("0xADDR", text)
    text = _HEX_OR_UUID.sub("HEX", text)
    text = _PATHLIKE.sub("PATH", text)
    text = _QUOTED.sub("STR", text)
    text = _NUMBER.sub("N", text)
    text = _WHITESPACE.sub(" ", text)
    return text.lower()[:200]


def _error_kind(message: str) -> str | None:
    """Best-effort exception class name from an error string (e.g. ValueError)."""
    # Common shapes: "ValueError: bad" or "<class 'TimeoutError'>" or "TimeoutError".
    match = re.match(r"\s*([A-Za-z_][\w.]*Error|[A-Za-z_][\w.]*Exception)\b", message)
    if match:
        return match.group(1).split(".")[-1]
    return None


def _tool_name(payload: Mapping[str, Any]) -> str | None:
    name = payload.get("tool") or payload.get("name") or payload.get("tool_name")
    return str(name) if name else None


@dataclass(frozen=True)
class FailureFingerprint:
    """The computed failure signature for a session.

    is_failure is False when no failure signal was found (the session succeeded);
    in that case fingerprint is an empty string. fingerprint is a short stable hex
    digest of the normalized signals. label is a one-line human summary. signals
    is the ordered list of normalized signal strings that fed the digest.
    """

    is_failure: bool
    fingerprint: str
    label: str
    signals: tuple[str, ...] = field(default_factory=tuple)


def _collect_signals(events: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    """Gather (signature_parts, human_labels) from a session's failure events.

    signature_parts are the normalized strings hashed into the fingerprint;
    human_labels are the readable counterparts for the summary. Never raises.
    """

    parts: list[str] = []
    labels: list[str] = []

    for event in events:
        try:
            etype = event.get("type")
            payload = event.get("payload")
            payload = payload if isinstance(payload, Mapping) else {}

            if etype == "error":
                message = str(payload.get("message") or payload.get("error") or "error")
                kind = _error_kind(message)
                norm = _normalize_message(message)
                parts.append(f"error:{kind or ''}:{norm}")
                labels.append(f"error {kind or norm[:48]}")
            elif etype == "tool_result" and (
                payload.get("error") or payload.get("status") in ("error", "failed")
            ):
                tool = _tool_name(payload) or "tool"
                message = str(payload.get("error") or "failed")
                parts.append(f"tool_error:{tool}:{_normalize_message(message)}")
                labels.append(f"tool {tool} failed")
            elif etype == "goal_check" and payload.get("passed") is False:
                mismatches = payload.get("mismatches")
                if isinstance(mismatches, (list, tuple)) and mismatches:
                    norm = _normalize_message(" ".join(str(m) for m in mismatches))
                else:
                    norm = "goal not met"
                parts.append(f"goal:{norm}")
                labels.append(f"goal mismatch: {norm[:48]}")
            elif etype == "session_end":
                status = payload.get("status")
                err = payload.get("error")
                if status is not None and status != "completed":
                    parts.append(f"status:{status}")
                    labels.append(f"session {status}")
                if err:
                    norm = _normalize_message(str(err))
                    parts.append(f"end_error:{norm}")
                    labels.append(f"ended with error {norm[:48]}")
        except Exception:  # pragma: no cover - fingerprinting must never raise
            continue

    return parts, labels


def failure_fingerprint(events: Sequence[Mapping[str, Any]]) -> FailureFingerprint:
    """Compute a stable failure fingerprint for a session. Pure, never raises.

    Returns a FailureFingerprint whose is_failure is False (and fingerprint empty)
    when the session shows no failure signal. When it does, the fingerprint is a
    12-character hex digest derived from the normalized error kind, failing tool,
    and goal mismatch, so the same class of failure across runs shares an id.
    """

    try:
        parts, labels = _collect_signals(events)
    except Exception:  # pragma: no cover - defensive
        parts, labels = [], []

    if not parts:
        return FailureFingerprint(is_failure=False, fingerprint="", label="no failure detected")

    # Order-independent within a session: the same set of signals fingerprints
    # the same regardless of event ordering jitter.
    canonical = "|".join(sorted(set(parts)))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    # The label leads with the first (most salient) signal, deduplicated.
    seen: set[str] = set()
    unique_labels: list[str] = []
    for x in labels:
        if x not in seen:
            seen.add(x)
            unique_labels.append(x)
    label = unique_labels[0] if unique_labels else "failure"
    if len(unique_labels) > 1:
        label = f"{label} (+{len(unique_labels) - 1} more)"

    return FailureFingerprint(
        is_failure=True,
        fingerprint=digest,
        label=label,
        signals=tuple(sorted(set(parts))),
    )


__all__ = ["FailureFingerprint", "failure_fingerprint"]
