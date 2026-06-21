"""Tail-based sampling policy.

This is the on-thesis differentiator: rather than recording every run, keep the
runs that matter (failures and anomalies) in full and drop boring successes down
to a small baseline. The policy here is a pure function of a buffered event list,
so the keep/drop decision is deterministic, testable, and side-effect free.

Session buffers events when tail_sample is on and, at end(), calls a policy to
decide whether the whole session is interesting. Interesting sessions flush in
full; boring successes fall through to a keep-rate (defaulting to the head
sample_rate so existing behavior is preserved).

The signals that make a session interesting:
- an error event
- a goal_check that did not pass
- a session_end whose status is not completed, or that carries an error
- a retry loop: the same tool call repeated at or above a threshold
- a latency outlier: a single span, or the whole session, slower than a threshold
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class TailDecision:
    """The outcome of a tail-sampling evaluation.

    keep is the final keep-or-drop verdict. interesting is True when a strong
    keep signal fired (as opposed to a boring success that happened to win the
    keep-rate lottery). reason is a short human-readable explanation, useful for
    observability and for the drop skeleton.
    """

    keep: bool
    interesting: bool
    reason: str


def _hash_fraction(key: str) -> float:
    """Deterministic fraction in [0, 1) from a string key (same scheme as head)."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, "big") / float(1 << 64)


def _tool_signature(event: Mapping[str, Any]) -> str | None:
    """Stable signature for a tool_call (name + normalized args) for retry detection."""
    payload = event.get("payload") or {}
    if not isinstance(payload, Mapping):
        return None
    name = payload.get("tool") or payload.get("name") or payload.get("tool_name")
    if not name:
        return None
    args = payload.get("arguments")
    if args is None:
        args = payload.get("args")
    try:
        normalized = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        normalized = str(args)
    return f"{name}::{normalized}"


@dataclass(frozen=True)
class TailSamplingPolicy:
    """Tunable policy that decides whether a buffered session is worth keeping.

    retry_loop_threshold: keep a session where one identical tool call repeats at
        least this many times (a likely stuck loop).
    span_latency_ms_threshold: keep a session containing any single span slower
        than this many milliseconds.
    session_latency_ms_threshold: keep a session whose total span time exceeds
        this many milliseconds.
    boring_success_keep_rate: keep-rate applied to boring successes. None means
        defer to the session's head sample_rate, which preserves existing
        behavior; set a small value (for example 0.05) to keep a baseline sample.
    emit_skeleton_on_drop: when True, a dropped session still emits a minimal
        skeleton (its opening event plus its session_end, annotated with the drop
        reason and the original event count) so downstream knows the run happened.
        Default False keeps the original all-or-nothing drop.
    """

    retry_loop_threshold: int = 3
    span_latency_ms_threshold: float = 30_000.0
    session_latency_ms_threshold: float = 120_000.0
    boring_success_keep_rate: float | None = None
    emit_skeleton_on_drop: bool = False

    def interesting(self, events: Sequence[Mapping[str, Any]]) -> tuple[bool, str]:
        """Pure check: did any strong keep signal fire? Returns (interesting, reason).

        Never raises; a malformed event is simply skipped. The first signal to
        fire wins the reason, in priority order (failures before anomalies).
        """

        retry_counts: Counter[str] = Counter()
        total_span_ms = 0.0
        slow_span: tuple[str, float] | None = None

        for event in events:
            try:
                etype = event.get("type")
                payload = event.get("payload")
                payload = payload if isinstance(payload, Mapping) else {}

                if etype == "error":
                    return True, "error event"
                if etype == "goal_check" and payload.get("passed") is False:
                    return True, "failed goal_check"
                if etype == "session_end":
                    status = payload.get("status")
                    if (status is not None and status != "completed") or payload.get(
                        "error"
                    ):
                        return True, "session ended with failure"

                if etype == "tool_call":
                    sig = _tool_signature(event)
                    if sig is not None:
                        retry_counts[sig] += 1

                is_span_end = etype == "span_end" or (
                    etype == "state_change" and payload.get("name") == "span_end"
                )
                if is_span_end:
                    duration = payload.get("duration_ms")
                    if isinstance(duration, (int, float)) and not isinstance(
                        duration, bool
                    ):
                        total_span_ms += float(duration)
                        if duration > self.span_latency_ms_threshold and (
                            slow_span is None or duration > slow_span[1]
                        ):
                            name = (
                                payload.get("span_name")
                                or payload.get("name")
                                or "span"
                            )
                            slow_span = (str(name), float(duration))
            except Exception:  # pragma: no cover - evaluation must never raise
                continue

        if retry_counts:
            sig, count = retry_counts.most_common(1)[0]
            if count >= self.retry_loop_threshold:
                tool = sig.split("::", 1)[0]
                return True, f"retry loop on {tool} (x{count})"

        if slow_span is not None:
            return True, f"slow span {slow_span[0]} ({int(slow_span[1])}ms)"

        if total_span_ms > self.session_latency_ms_threshold:
            return True, f"slow session ({int(total_span_ms)}ms of span time)"

        return False, "boring success"

    def decide(
        self,
        events: Sequence[Mapping[str, Any]],
        *,
        session_id: str,
        head_sample_rate: float,
    ) -> TailDecision:
        """Final keep-or-drop verdict for a buffered session. Pure and deterministic.

        An interesting session is always kept. A boring success is kept at
        boring_success_keep_rate when set, otherwise at the head sample_rate, and
        the choice is a deterministic function of session_id so it is reproducible.
        """

        is_interesting, reason = self.interesting(events)
        if is_interesting:
            return TailDecision(keep=True, interesting=True, reason=reason)

        rate = (
            head_sample_rate
            if self.boring_success_keep_rate is None
            else self.boring_success_keep_rate
        )
        if rate >= 1.0:
            keep = True
        elif rate <= 0.0:
            keep = False
        else:
            keep = _hash_fraction(session_id) < rate
        return TailDecision(
            keep=keep,
            interesting=False,
            reason="boring success (kept)" if keep else "boring success (dropped)",
        )


# The default policy: thresholds tuned for typical agent runs, and a None boring
# keep-rate so a plain tail_sample=True behaves exactly as before (boring keep is
# governed by the head sample_rate) unless the caller opts into a tighter rate.
DEFAULT_TAIL_POLICY = TailSamplingPolicy()


__all__ = ["DEFAULT_TAIL_POLICY", "TailDecision", "TailSamplingPolicy"]
