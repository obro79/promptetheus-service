"""Rule detectors — the differentiated core of Promptetheus analysis.

Each detector is a *pure* function over a session's ordered events plus the
session's user_goal. They perform no I/O and no store access, and they are
deterministic: the same events in produce the same Detection out. The engine
(server/analysis/engine.py) runs them via ALL_DETECTORS and aggregates
the results into an AnalysisResult.

Behavior here is contract, not implementation detail — see the "Detector
Semantics" section of docs/architecture/technical-architecture.md and section
1 of server/INTERNAL_CONTRACT.md. Confidence values, evidence rules, and the
critical-step rule are frozen.
"""

from __future__ import annotations

from typing import Any

from promptetheus.server.models import Detection

# ---------------------------------------------------------------------------
# Shared helpers (pure)
# ---------------------------------------------------------------------------

# Phrases that, in a terminal agent_message, assert completion/success.
_SUCCESS_PHRASES: tuple[str, ...] = ("done", "booked", "completed", "successfully")

# Phrases that introduce a stop-boundary inside a user_goal.
_BOUNDARY_MARKERS: tuple[str, ...] = (
    "stop at",
    "stop before",
    "do not",
    "don't",
    "without",
)

# Browser actions that progress a flow forward.
_PROGRESSING_ACTIONS: tuple[str, ...] = (
    "click",
    "fill",
    "type",
    "submit",
    "confirm",
    "press",
)

# Browser actions that finalize / commit a flow (stronger confidence signals).
_FINALIZING_ACTIONS: tuple[str, ...] = ("submit", "confirm")


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    """Return an event's payload as a dict (empty dict if missing/non-dict)."""

    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _seq(event: dict[str, Any]) -> int:
    """Return an event's seq (events are pre-sorted by the caller)."""

    seq = event.get("seq")
    return seq if isinstance(seq, int) and not isinstance(seq, bool) else 0


def _events_of_type(
    events: list[dict[str, Any]], event_type: str
) -> list[dict[str, Any]]:
    """Return events of a given type, preserving the input (seq) order."""

    return [event for event in events if event.get("type") == event_type]


def _action_kind(event: dict[str, Any]) -> str:
    """Return the lowercased action of a browser_action payload."""

    return str(_payload(event).get("action", "")).strip().lower()


def _is_progressing(event: dict[str, Any]) -> bool:
    """Whether a browser_action progresses the flow forward."""

    kind = _action_kind(event)
    return any(
        kind == marker or kind.startswith(marker) for marker in _PROGRESSING_ACTIONS
    )


def _is_finalizing(event: dict[str, Any]) -> bool:
    """Whether a browser_action submits/confirms (finalizes) the flow."""

    kind = _action_kind(event)
    return any(
        kind == marker or kind.startswith(marker) for marker in _FINALIZING_ACTIONS
    )


def _final_dom_snapshot(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the last dom_snapshot event (highest seq), or None."""

    snapshots = _events_of_type(events, "dom_snapshot")
    return snapshots[-1] if snapshots else None


def _goal_constraints(user_goal: str) -> list[str]:
    """Extract candidate target-value tokens from the user goal.

    Cheap, deterministic tokenization: lowercased alphanumeric words of length
    >= 3, minus a small stopword set. These are matched against the final
    selected_values / agent message to find contradictions. This is a
    heuristic, not a parser — the structured goal_check path is preferred.
    """

    stop = {
        "the",
        "and",
        "for",
        "with",
        "without",
        "stop",
        "dont",
        "not",
        "book",
        "please",
        "make",
        "set",
        "select",
        "choose",
        "from",
        "that",
        "this",
        "you",
        "your",
        "into",
        "onto",
        "but",
        "do",
        "at",
        "to",
        "a",
        "an",
    }
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in user_goal.lower().replace("-", " ").replace("/", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if len(word) < 3 or word in stop or word in seen:
            continue
        seen.add(word)
        tokens.append(word)
    return tokens


def _critical_step_for_value(
    events: list[dict[str, Any]], constraints: list[str], observed_seq: int
) -> int:
    """Find the earliest browser_action that set a value contradicting the goal.

    Returns the lowest matching browser_action seq, or observed_seq when
    no contributing action can be attributed (the snapshot then stands in for
    the critical step). Per the contract, the critical step is the action that
    *caused* the wrong state, not the snapshot that observed it.
    """

    best: int | None = None
    for event in _events_of_type(events, "browser_action"):
        seq = _seq(event)
        if seq > observed_seq:
            continue
        payload = _payload(event)
        haystack = " ".join(
            str(payload.get(field, ""))
            for field in ("target", "value", "url", "metadata")
        ).lower()
        if any(token in haystack for token in constraints):
            if best is None or seq < best:
                best = seq
    return best if best is not None else observed_seq


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens of length >= 3 from arbitrary text."""

    tokens: list[str] = []
    for raw in str(text).lower().replace("-", " ").replace("/", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if len(word) >= 3:
            tokens.append(word)
    return tokens


def _goal_check_mismatch_tokens(goal_check: dict[str, Any]) -> list[str]:
    """Tokenize the mismatches list of a failed goal_check event."""

    mismatches = _payload(goal_check).get("mismatches")
    if not isinstance(mismatches, list):
        return []
    tokens: list[str] = []
    for item in mismatches:
        tokens.extend(_tokenize(item))
    return tokens


def _selected_value_tokens(snapshot: dict[str, Any] | None) -> list[str]:
    """Tokenize a snapshot's selected_values (the values actually set)."""

    if snapshot is None:
        return []
    selected = _payload(snapshot).get("selected_values")
    if not isinstance(selected, dict):
        return []
    tokens: list[str] = []
    for value in selected.values():
        tokens.extend(_tokenize(value))
    return tokens


# ---------------------------------------------------------------------------
# browser_goal_mismatch
# ---------------------------------------------------------------------------


def detect_browser_goal_mismatch(
    events: list[dict[str, Any]], user_goal: str
) -> Detection | None:
    """Detect that the final browser state contradicts the user's goal.

    Tiered by signal strength (see Detector Semantics):

    - 0.9: an explicit goal_check with passed == False.
    - 0.7: the final dom_snapshot.selected_values contradicts a goal
      constraint.
    - 0.5: only the goal text vs the final agent_message disagree (no
      structured state available).

    Evidence: the failed goal_check (or final dom_snapshot) seq plus the
    earliest browser_action that set the contradicting value (the critical
    step).
    """

    constraints = _goal_constraints(user_goal)

    # Tier 1: explicit failed goal_check (conf 0.9).
    for event in _events_of_type(events, "goal_check"):
        if _payload(event).get("passed") is False:
            observed_seq = _seq(event)
            # The contradicting value(s): the goal_check's mismatches if present,
            # else the final snapshot's selected values. The critical step is the
            # earliest browser_action that set one of those wrong values.
            contradicting = _goal_check_mismatch_tokens(event)
            if not contradicting:
                contradicting = _selected_value_tokens(_final_dom_snapshot(events))
            critical = _critical_step_for_value(events, contradicting, observed_seq)
            evidence = sorted({observed_seq, critical})
            return Detection(
                label="browser_goal_mismatch",
                confidence=0.9,
                evidence_refs=evidence,
                critical_step_seq=critical,
            )

    # Tier 2: final dom_snapshot.selected_values contradicts the goal (conf 0.7).
    final_snapshot = _final_dom_snapshot(events)
    if final_snapshot is not None:
        selected = _payload(final_snapshot).get("selected_values")
        if isinstance(selected, dict) and selected:
            selected_blob = " ".join(str(value) for value in selected.values()).lower()
            # Goal names constraint tokens that the selected values do not honor.
            value_words: set[str] = set()
            for value in selected.values():
                for raw in (
                    str(value).lower().replace("-", " ").replace("/", " ").split()
                ):
                    value_words.add("".join(ch for ch in raw if ch.isalnum()))
            contradicted = [
                token
                for token in constraints
                if token not in value_words and token not in selected_blob
            ]
            if contradicted:
                observed_seq = _seq(final_snapshot)
                critical = _critical_step_for_value(events, contradicted, observed_seq)
                evidence = sorted({observed_seq, critical})
                return Detection(
                    label="browser_goal_mismatch",
                    confidence=0.7,
                    evidence_refs=evidence,
                    critical_step_seq=critical,
                )

    # Tier 3: goal text vs final agent_message disagreement (conf 0.5).
    agent_messages = _events_of_type(events, "agent_message")
    if constraints and agent_messages:
        final_msg = agent_messages[-1]
        content = str(_payload(final_msg).get("content", "")).lower()
        if content and not all(token in content for token in constraints):
            observed_seq = _seq(final_msg)
            critical = _critical_step_for_value(events, constraints, observed_seq)
            evidence = sorted({observed_seq, critical})
            return Detection(
                label="browser_goal_mismatch",
                confidence=0.5,
                evidence_refs=evidence,
                critical_step_seq=critical,
            )

    return None


# ---------------------------------------------------------------------------
# ignored_ui_warning
# ---------------------------------------------------------------------------


def detect_ignored_ui_warning(
    events: list[dict[str, Any]], user_goal: str
) -> Detection | None:
    """Detect that the agent progressed past a UI warning without addressing it.

    Fire when a dom_snapshot carries a non-empty warnings list and a later
    progressing browser_action (click/fill/submit) occurs with no intervening
    action addressing the warned field.

    Confidence: 0.9 when the warning persists into the final snapshot and the last
    progressing action is a submit/confirm; 0.6 when transient/positional.

    Evidence: the warning snapshot seq + the first progressing browser_action
    seq after it.
    """

    snapshots = _events_of_type(events, "dom_snapshot")
    final_snapshot = snapshots[-1] if snapshots else None
    final_warnings = (
        [str(w).lower() for w in _payload(final_snapshot).get("warnings", [])]
        if final_snapshot is not None
        and isinstance(_payload(final_snapshot).get("warnings"), list)
        else []
    )

    for snapshot in snapshots:
        warnings = _payload(snapshot).get("warnings")
        if not isinstance(warnings, list) or not warnings:
            continue
        warning_seq = _seq(snapshot)

        # First progressing browser_action strictly after the warning snapshot.
        progressing = next(
            (
                event
                for event in _events_of_type(events, "browser_action")
                if _seq(event) > warning_seq and _is_progressing(event)
            ),
            None,
        )
        if progressing is None:
            continue

        # An intervening action that addresses the warned field clears the issue.
        if _warning_addressed(events, warnings, warning_seq, _seq(progressing)):
            continue

        action_seq = _seq(progressing)

        # The warning persists into the final snapshot and the flow was finalized.
        warning_persists = bool(final_warnings) and final_snapshot is not None
        last_progressing = _last_progressing_action(events)
        finalized = last_progressing is not None and _is_finalizing(last_progressing)
        if warning_persists and finalized:
            confidence = 0.9
        else:
            confidence = 0.6

        evidence = sorted({warning_seq, action_seq})
        return Detection(
            label="ignored_ui_warning",
            confidence=confidence,
            evidence_refs=evidence,
            critical_step_seq=action_seq,
        )

    return None


def _warning_addressed(
    events: list[dict[str, Any]],
    warnings: list[Any],
    warning_seq: int,
    action_seq: int,
) -> bool:
    """Whether a browser_action between the warning and the progressing action
    addressed the warned-about field (heuristic token overlap on target/value)."""

    warning_tokens: set[str] = set()
    for warning in warnings:
        for raw in str(warning).lower().replace("-", " ").split():
            token = "".join(ch for ch in raw if ch.isalnum())
            if len(token) >= 3:
                warning_tokens.add(token)
    if not warning_tokens:
        return False

    for event in _events_of_type(events, "browser_action"):
        seq = _seq(event)
        if seq <= warning_seq or seq >= action_seq:
            continue
        payload = _payload(event)
        haystack = " ".join(
            str(payload.get(field, "")) for field in ("target", "value", "url")
        ).lower()
        if any(token in haystack for token in warning_tokens):
            return True
    return False


def _last_progressing_action(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the last progressing browser_action in the session, or None."""

    progressing = [
        event
        for event in _events_of_type(events, "browser_action")
        if _is_progressing(event)
    ]
    return progressing[-1] if progressing else None


# ---------------------------------------------------------------------------
# false_success_claim (runs LAST — depends on prior detections)
# ---------------------------------------------------------------------------


def detect_false_success_claim(
    events: list[dict[str, Any]],
    user_goal: str,
    prior: dict[str, Detection],
) -> Detection | None:
    """Detect a terminal success claim that contradicts the actual outcome.

    Fire when a terminal agent_message asserts completion/success (phrase set
    "done"/"booked"/"completed"/"successfully", or metadata.status == "success")
    AND either browser_goal_mismatch fired or the terminal goal_check.passed
    is false.

    Confidence: 0.95 when paired with a >= 0.7 goal mismatch; 0.6 when the mismatch
    is itself low-confidence (0.5).

    Evidence: the claiming agent_message seq + the mismatch evidence refs.
    """

    claim = _terminal_success_claim(events)
    if claim is None:
        return None
    claim_seq = _seq(claim)

    mismatch = prior.get("browser_goal_mismatch")
    goal_failed = _terminal_goal_check_failed(events)

    if mismatch is None and goal_failed is None:
        return None

    # Confidence keys off the strength of the paired goal mismatch.
    if mismatch is not None and mismatch.confidence >= 0.7:
        confidence = 0.95
    elif mismatch is not None and mismatch.confidence == 0.5:
        confidence = 0.6
    elif goal_failed is not None:
        # A failed terminal goal_check is itself a strong (>=0.7-equivalent) signal.
        confidence = 0.95
    else:
        confidence = 0.6

    evidence_refs = [claim_seq]
    if mismatch is not None:
        evidence_refs.extend(mismatch.evidence_refs)
    if goal_failed is not None:
        evidence_refs.append(goal_failed)
    evidence_refs = sorted(set(evidence_refs))

    return Detection(
        label="false_success_claim",
        confidence=confidence,
        evidence_refs=evidence_refs,
        critical_step_seq=claim_seq,
    )


def _terminal_success_claim(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the terminal agent_message that asserts success, or None.

    "Terminal" = the last agent_message in the session; it must assert success
    via the phrase set or a structured metadata.status == "success".
    """

    agent_messages = _events_of_type(events, "agent_message")
    if not agent_messages:
        return None
    final_msg = agent_messages[-1]
    payload = _payload(final_msg)

    metadata = final_msg.get("metadata")
    if (
        isinstance(metadata, dict)
        and str(metadata.get("status", "")).lower() == "success"
    ):
        return final_msg
    payload_meta = payload.get("metadata")
    if (
        isinstance(payload_meta, dict)
        and str(payload_meta.get("status", "")).lower() == "success"
    ):
        return final_msg

    content = str(payload.get("content", "")).lower()
    if any(phrase in content for phrase in _SUCCESS_PHRASES):
        return final_msg
    return None


def _terminal_goal_check_failed(events: list[dict[str, Any]]) -> int | None:
    """Return the seq of the terminal goal_check if it failed, else None."""

    goal_checks = _events_of_type(events, "goal_check")
    if not goal_checks:
        return None
    last = goal_checks[-1]
    if _payload(last).get("passed") is False:
        return _seq(last)
    return None


# ---------------------------------------------------------------------------
# forbidden_action
# ---------------------------------------------------------------------------


def detect_forbidden_action(
    events: list[dict[str, Any]], user_goal: str
) -> Detection | None:
    """Detect a browser_action that crosses a stop-boundary named in the goal.

    Parse user_goal for a stop-boundary ("stop at", "don't", "do not",
    "without"); fire when a browser_action crosses it.

    Confidence: 0.9 on a selector/target-level match of the boundary element; 0.6
    on a visible-text heuristic match only.

    Evidence: the crossing browser_action seq + the boundary-reaching
    dom_snapshot seq.
    """

    boundary_tokens = _boundary_tokens(user_goal)
    if not boundary_tokens:
        return None

    for event in _events_of_type(events, "browser_action"):
        if not _is_progressing(event):
            continue
        payload = _payload(event)
        target_blob = " ".join(
            str(payload.get(field, "")) for field in ("target", "url", "value")
        ).lower()
        selector_match = any(token in target_blob for token in boundary_tokens)

        action_seq = _seq(event)
        boundary_snapshot_seq = _boundary_snapshot_seq(
            events, boundary_tokens, action_seq
        )

        if selector_match:
            confidence = 0.9
        elif boundary_snapshot_seq is not None:
            # Visible-text heuristic: the boundary was reached (a snapshot's
            # visible_text names it) and a progressing action then crossed it.
            confidence = 0.6
        else:
            continue

        evidence = [action_seq]
        if boundary_snapshot_seq is not None:
            evidence.append(boundary_snapshot_seq)
        evidence = sorted(set(evidence))
        return Detection(
            label="forbidden_action",
            confidence=confidence,
            evidence_refs=evidence,
            critical_step_seq=action_seq,
        )

    return None


def _boundary_tokens(user_goal: str) -> list[str]:
    """Extract boundary value tokens from a goal's stop/limit phrase.

    Finds a marker ("stop at", "do not", "don't", "without") and returns the
    significant words that follow it, which name the forbidden element/screen.
    """

    lowered = user_goal.lower()
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "at",
        "on",
        "of",
        "do",
        "not",
        "any",
        "it",
        "is",
        "be",
        "page",
        "button",
        "screen",
        "step",
    }
    tokens: list[str] = []
    for marker in _BOUNDARY_MARKERS:
        index = lowered.find(marker)
        if index == -1:
            continue
        tail = lowered[index + len(marker) :]
        # Take the clause up to the next sentence/clause break.
        for stopper in (".", ";", ",", " and ", " then "):
            cut = tail.find(stopper)
            if cut != -1:
                tail = tail[:cut]
        for raw in tail.replace("-", " ").replace("/", " ").split():
            word = "".join(ch for ch in raw if ch.isalnum())
            if len(word) >= 3 and word not in stop and word not in tokens:
                tokens.append(word)
    return tokens


def _boundary_snapshot_seq(
    events: list[dict[str, Any]], boundary_tokens: list[str], action_seq: int
) -> int | None:
    """Return the seq of a dom_snapshot at/before the action whose visible_text
    names the boundary (the boundary screen was reached), else None."""

    best: int | None = None
    for snapshot in _events_of_type(events, "dom_snapshot"):
        seq = _seq(snapshot)
        if seq > action_seq:
            continue
        visible_text = str(_payload(snapshot).get("visible_text", "")).lower()
        if any(token in visible_text for token in boundary_tokens):
            best = seq  # keep the latest qualifying snapshot before the action
    return best


# ---------------------------------------------------------------------------
# Registry + root cause
# ---------------------------------------------------------------------------

# Ordered registry the engine iterates. false_success_claim depends on the
# prior detections, so it runs LAST and receives {label: Detection} of what
# has fired so far. Each entry is (label, fn, needs_prior).
ALL_DETECTORS: list[tuple[str, Any, bool]] = [
    ("browser_goal_mismatch", detect_browser_goal_mismatch, False),
    ("ignored_ui_warning", detect_ignored_ui_warning, False),
    ("forbidden_action", detect_forbidden_action, False),
    ("false_success_claim", detect_false_success_claim, True),
]


# Human-readable goal-constraint phrasing + the missing safeguard, per label.
_LABEL_CONSTRAINT: dict[str, str] = {
    "browser_goal_mismatch": "the user's stated goal",
    "ignored_ui_warning": "a surfaced UI warning",
    "false_success_claim": "the actual final outcome",
    "forbidden_action": "the goal's stop-boundary",
}

_LABEL_SAFEGUARD: dict[str, str] = {
    "browser_goal_mismatch": "no final outcome verification before claiming success",
    "ignored_ui_warning": "no check that surfaced warnings were resolved before proceeding",
    "false_success_claim": "no final outcome verification before claiming success",
    "forbidden_action": "no stop-boundary guard before the committing action",
}


def root_cause_sentence(detections: list[Detection], user_goal: str) -> str:
    """Template-generated, single-sentence root cause (no LLM in State 0).

    Names the critical step, the contradicted goal constraint, and the missing
    safeguard, derived from the highest-confidence fired detection.
    """

    if not detections:
        return "No failure detected: the run satisfied its goal."

    primary = max(detections, key=lambda detection: detection.confidence)
    constraint = _LABEL_CONSTRAINT.get(primary.label, "the user goal")
    safeguard = _LABEL_SAFEGUARD.get(primary.label, "no verification before completion")

    if primary.critical_step_seq is not None:
        step_phrase = f"the action at step {primary.critical_step_seq}"
    else:
        step_phrase = "the failing action"

    goal_text = user_goal.strip()
    goal_clause = f' for goal "{goal_text}"' if goal_text else ""

    return (
        f"{step_phrase} contradicted {constraint}{goal_clause}; "
        f"root cause: {safeguard}."
    )


__all__ = [
    "ALL_DETECTORS",
    "detect_browser_goal_mismatch",
    "detect_false_success_claim",
    "detect_forbidden_action",
    "detect_ignored_ui_warning",
    "root_cause_sentence",
]
