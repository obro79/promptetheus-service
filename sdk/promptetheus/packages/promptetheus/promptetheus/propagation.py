"""W3C Trace Context propagation for distributed agent runs.

When an agent spans multiple processes or services, each one opens its own
Promptetheus session. This module lets those sessions link into one logical
trace by carrying a trace id (and the calling span) across a service boundary in
a standard traceparent HTTP header.

It is dependency-free and pure: generate a context, inject it into outgoing
headers, extract it from incoming headers, and derive Session kwargs from it so a
downstream service starts a session that records where it came from. Parsing is
tolerant: a missing or malformed header yields None and never raises.

traceparent format (W3C Trace Context, version 00):

    version "-" trace_id "-" parent_id "-" flags
    00-<32 hex trace id>-<16 hex span id>-<2 hex flags>
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

_TRACEPARENT_HEADER = "traceparent"
_VERSION = "00"
_DEFAULT_FLAGS = "01"  # sampled

# 00-<32 hex>-<16 hex>-<2 hex>; we accept any version byte but emit "00".
_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-"
    r"(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<parent_id>[0-9a-f]{16})-"
    r"(?P<flags>[0-9a-f]{2})$"
)

_ALL_ZERO_TRACE = "0" * 32
_ALL_ZERO_SPAN = "0" * 16


@dataclass(frozen=True)
class TraceContext:
    """A propagated trace position.

    trace_id is the 32-hex id shared by every session in the distributed trace;
    parent_id is the 16-hex id of the span that made the outgoing call (the
    parent of whatever the downstream service does). flags is the 2-hex W3C
    trace-flags byte (01 = sampled).
    """

    trace_id: str
    parent_id: str
    flags: str = _DEFAULT_FLAGS

    def to_traceparent(self) -> str:
        return f"{_VERSION}-{self.trace_id}-{self.parent_id}-{self.flags}"


def _random_hex(n_bytes: int) -> str:
    return os.urandom(n_bytes).hex()


def new_trace_context() -> TraceContext:
    """Mint a fresh trace context with random, valid (non-zero) ids."""

    trace_id = _random_hex(16)
    if trace_id == _ALL_ZERO_TRACE:  # astronomically unlikely; stay valid
        trace_id = "0" * 31 + "1"
    parent_id = _random_hex(8)
    if parent_id == _ALL_ZERO_SPAN:
        parent_id = "0" * 15 + "1"
    return TraceContext(trace_id=trace_id, parent_id=parent_id)


def inject(
    context: TraceContext, headers: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return headers (copied) with a traceparent set from context.

    Pass your outgoing request headers; the returned dict is safe to send.
    """

    out: dict[str, str] = dict(headers or {})
    out[_TRACEPARENT_HEADER] = context.to_traceparent()
    return out


def extract(headers: Mapping[str, str] | None) -> TraceContext | None:
    """Parse a TraceContext from incoming headers, or None.

    Tolerant: missing header, wrong shape, or all-zero ids return None. Header
    lookup is case-insensitive. Never raises.
    """

    if not headers:
        return None
    value = None
    for key, val in headers.items():
        if isinstance(key, str) and key.lower() == _TRACEPARENT_HEADER:
            value = val
            break
    if not isinstance(value, str):
        return None
    match = _TRACEPARENT_RE.match(value.strip().lower())
    if match is None:
        return None
    trace_id = match.group("trace_id")
    parent_id = match.group("parent_id")
    if trace_id == _ALL_ZERO_TRACE or parent_id == _ALL_ZERO_SPAN:
        return None
    return TraceContext(
        trace_id=trace_id, parent_id=parent_id, flags=match.group("flags")
    )


def session_kwargs_from_context(context: TraceContext) -> dict[str, Any]:
    """Derive trace.start / Session kwargs that record an incoming trace context.

    Splat the result into trace.start so the downstream session carries the
    distributed trace id and the calling span in its metadata:

        ctx = extract(request.headers)
        with trace.start(agent="svc-b", user_goal="...",
                         **session_kwargs_from_context(ctx)) as s:
            ...
    """

    return {
        "metadata": {
            "trace_id": context.trace_id,
            "parent_span_id": context.parent_id,
            "trace_flags": context.flags,
        }
    }


__all__ = [
    "TraceContext",
    "extract",
    "inject",
    "new_trace_context",
    "session_kwargs_from_context",
]
