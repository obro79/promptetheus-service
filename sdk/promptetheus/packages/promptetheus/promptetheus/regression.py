"""Session-to-session diffing and regression assertions.

Two runs of the same agent should do roughly the same thing. This module turns a
flat event stream into an ordered list of salient steps (built on top of the run
tree from trace_tree), then diffs two sessions: which steps were added, removed,
or changed, and whether the second session regressed (a step that passed before
now fails, or a new error appeared).

It is dependency-free and never raises on malformed input, so it is safe to call
from a user's own test suite via assert_no_regression.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .trace_tree import build_trace_forest


@dataclass(frozen=True)
class Step:
    """One salient step in a session.

    key is stable across runs with the same structure (kind, identity, and the
    ordinal occurrence of that identity). label is human-readable. ok is False
    when the step represents a failure (an error, a failed goal_check, or a
    tool_result carrying an error). duration_ms is set for span steps when known.
    """

    key: str
    kind: str
    label: str
    ok: bool = True
    duration_ms: float | None = None


@dataclass(frozen=True)
class StepChange:
    """A single difference between two sessions."""

    key: str
    kind: str  # added | removed | changed
    detail: str
    regressed: bool = False


@dataclass(frozen=True)
class SessionDiff:
    """The structured result of diffing two sessions."""

    added: list[Step] = field(default_factory=list)
    removed: list[Step] = field(default_factory=list)
    changed: list[StepChange] = field(default_factory=list)
    regressed: bool = False

    @property
    def changes(self) -> list[StepChange]:
        """All differences as StepChange records, in a stable order."""
        out = [StepChange(s.key, "added", s.label) for s in self.added]
        out += [StepChange(s.key, "removed", s.label) for s in self.removed]
        out += list(self.changed)
        return out

    def summary(self) -> str:
        """A short multi-line summary, empty string when the sessions match."""
        if not self.added and not self.removed and not self.changed:
            return ""
        lines = []
        for step in self.added:
            lines.append(f"+ added {step.label}")
        for step in self.removed:
            lines.append(f"- removed {step.label}")
        for change in self.changed:
            mark = "! regressed" if change.regressed else "~ changed"
            lines.append(f"{mark} {change.detail}")
        return "\n".join(lines)


# Materially-different span duration: at least this ratio and absolute gap so a
# tiny jitter is not reported as a change.
_DURATION_RATIO = 2.0
_DURATION_ABS_MS = 250.0


def _flatten(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Ordered event walk derived from the reconstructed run tree.

    Going through build_trace_forest gives a coherent, span-aware ordering and
    exercises the same reconstruction used by replay; on any failure it falls
    back to the events as given so diffing still works.
    """

    try:
        ordered: list[Mapping[str, Any]] = []

        def walk(node: Any) -> None:
            for ev in node.events:
                if isinstance(ev, Mapping):
                    ordered.append(ev)
            for child in node.children:
                walk(child)

        for root in build_trace_forest(events):
            walk(root)
        if ordered:
            return ordered
    except Exception:
        pass
    return [e for e in events if isinstance(e, Mapping)]


def _tool_name(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("tool") or payload.get("name") or payload.get("tool_name") or "tool"
    )


def extract_steps(events: Sequence[Mapping[str, Any]]) -> list[Step]:
    """Reduce a session to its salient, comparable steps. Never raises.

    Steps are emitted for tool calls, goal checks, errors, failed tool results,
    and spans (for duration). Each step's key carries an ordinal so repeated
    identical steps stay distinguishable and align positionally across runs.
    """

    steps: list[Step] = []
    seen: Counter[str] = Counter()

    def add(
        kind: str, identity: str, label: str, ok: bool, duration: float | None
    ) -> None:
        base = f"{kind}:{identity}"
        seen[base] += 1
        steps.append(
            Step(
                key=f"{base}#{seen[base]}",
                kind=kind,
                label=label,
                ok=ok,
                duration_ms=duration,
            )
        )

    for event in _flatten(events):
        try:
            etype = event.get("type")
            payload = event.get("payload")
            payload = payload if isinstance(payload, Mapping) else {}

            if etype == "tool_call":
                name = _tool_name(payload)
                add("tool_call", name, f"tool_call {name}", True, None)
            elif etype == "tool_result":
                name = _tool_name(payload)
                err = payload.get("error") or payload.get("status") in (
                    "error",
                    "failed",
                )
                add("tool_result", name, f"tool_result {name}", not err, None)
            elif etype == "goal_check":
                passed = payload.get("passed") is not False
                add("goal_check", "goal", "goal_check", passed, None)
            elif etype == "error":
                msg = payload.get("message") or payload.get("error") or "error"
                add("error", str(msg)[:40], f"error {str(msg)[:40]}", False, None)
            elif etype == "span_end":
                name = str(payload.get("name") or "span")
                dur = payload.get("duration_ms")
                dur = (
                    float(dur)
                    if isinstance(dur, (int, float)) and not isinstance(dur, bool)
                    else None
                )
                add("span", name, f"span {name}", True, dur)
        except Exception:
            continue
    return steps


def diff_sessions(
    events_a: Sequence[Mapping[str, Any]],
    events_b: Sequence[Mapping[str, Any]],
) -> SessionDiff:
    """Diff session B against baseline session A. Never raises.

    regressed is True when a step that succeeded in A fails in B, or a new
    failure step (error or failed tool_result) appears in B that was not in A.
    """

    steps_a = {s.key: s for s in extract_steps(events_a)}
    steps_b = {s.key: s for s in extract_steps(events_b)}

    added = [s for k, s in steps_b.items() if k not in steps_a]
    removed = [s for k, s in steps_a.items() if k not in steps_b]
    changed: list[StepChange] = []
    regressed = False

    for key, b in steps_b.items():
        a = steps_a.get(key)
        if a is None:
            # A brand-new failure in B is a regression.
            if not b.ok:
                regressed = True
            continue
        if a.ok and not b.ok:
            changed.append(
                StepChange(
                    key,
                    "changed",
                    f"{b.label} passed before, now fails",
                    regressed=True,
                )
            )
            regressed = True
        elif not a.ok and b.ok:
            changed.append(
                StepChange(key, "changed", f"{b.label} failed before, now passes")
            )
        elif a.duration_ms and b.duration_ms:
            ratio = b.duration_ms / a.duration_ms if a.duration_ms else 1.0
            if (ratio >= _DURATION_RATIO or ratio <= 1 / _DURATION_RATIO) and abs(
                b.duration_ms - a.duration_ms
            ) >= _DURATION_ABS_MS:
                changed.append(
                    StepChange(
                        key,
                        "changed",
                        f"{b.label} duration {int(a.duration_ms)}ms -> {int(b.duration_ms)}ms",
                    )
                )

    return SessionDiff(
        added=added, removed=removed, changed=changed, regressed=regressed
    )


def assert_no_regression(
    golden_events: Sequence[Mapping[str, Any]],
    candidate_events: Sequence[Mapping[str, Any]],
) -> None:
    """Raise AssertionError if candidate regressed against golden, else return.

    Intended for users' own test suites: capture a known-good session as the
    golden baseline, then assert a new run did not introduce failures.
    """

    diff = diff_sessions(golden_events, candidate_events)
    if diff.regressed:
        raise AssertionError("Session regressed against golden:\n" + diff.summary())


__all__ = [
    "SessionDiff",
    "Step",
    "StepChange",
    "assert_no_regression",
    "diff_sessions",
    "extract_steps",
]
