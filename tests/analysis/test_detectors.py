"""Detector contract tests (P26.8).

Each of the four rule detectors is exercised with:

- a POSITIVE case that fires with the EXACT confidence + evidence/critical-step
  mandated by the "Detector Semantics" section of
  docs/architecture/technical-architecture.md (and section 1 of
  server/INTERNAL_CONTRACT.md), and
- at least one NEGATIVE case that does not fire.

Events are built as plain envelope dicts (type/session_id/timestamp/
seq/idempotency_key/payload[/metadata]) so the tests assert against
the real detector functions, not a mocked surface.

Tests run from the repo root: we put packages/promptetheus on sys.path
the same way tests/schema does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.server.analysis.detectors import (  # noqa: E402
    ALL_DETECTORS,
    detect_browser_goal_mismatch,
    detect_false_success_claim,
    detect_forbidden_action,
    detect_ignored_ui_warning,
    root_cause_sentence,
)
from promptetheus.server.models import Detection  # noqa: E402


# ---------------------------------------------------------------------------
# Event builders (plain envelope dicts)
# ---------------------------------------------------------------------------

SESSION_ID = "sess_test"


def _event(event_type: str, seq: int, payload: dict, metadata: dict | None = None) -> dict:
    event: dict = {
        "type": event_type,
        "session_id": SESSION_ID,
        "timestamp": "2026-06-12T12:00:00.000Z",
        "seq": seq,
        "idempotency_key": f"{SESSION_ID}:nonce:{seq}",
        "payload": payload,
    }
    if metadata is not None:
        event["metadata"] = metadata
    return event


def user_message(seq: int, content: str) -> dict:
    return _event("user_message", seq, {"content": content})


def agent_message(seq: int, content: str, metadata: dict | None = None) -> dict:
    return _event("agent_message", seq, {"content": content}, metadata=metadata)


def browser_action(seq: int, action: str, target: str = "", value: str = "", url: str = "") -> dict:
    return _event(
        "browser_action",
        seq,
        {"action": action, "target": target, "value": value, "url": url},
    )


def dom_snapshot(
    seq: int,
    *,
    selected_values: dict | None = None,
    warnings: list | None = None,
    visible_text: str = "",
) -> dict:
    payload: dict = {"visible_text": visible_text}
    if selected_values is not None:
        payload["selected_values"] = selected_values
    if warnings is not None:
        payload["warnings"] = warnings
    return _event("dom_snapshot", seq, payload)


def goal_check(seq: int, *, passed: bool, mismatches: list | None = None) -> dict:
    payload: dict = {"passed": passed}
    if mismatches is not None:
        payload["mismatches"] = mismatches
    return _event("goal_check", seq, payload)


# ===========================================================================
# browser_goal_mismatch
# ===========================================================================


def test_browser_goal_mismatch_fires_on_failed_goal_check_conf_0_9() -> None:
    """Tier 1: an explicit failed goal_check fires at 0.9.

    The critical step is the earliest browser_action that set a value named in
    the goal_check mismatches (tuesday), i.e. the seq-2 fill, not the
    snapshot/goal_check that observed it. Evidence carries that critical step plus
    the failed goal_check seq.
    """

    events = [
        user_message(1, "Book a Monday slot"),
        browser_action(2, "fill", target="day", value="Tuesday"),
        dom_snapshot(3, selected_values={"day": "Tuesday"}),
        goal_check(4, passed=False, mismatches=["day should be Monday but was Tuesday"]),
    ]

    detection = detect_browser_goal_mismatch(events, "Book a Monday slot")

    assert detection is not None
    assert detection.label == "browser_goal_mismatch"
    assert detection.confidence == 0.9
    assert detection.critical_step_seq == 2
    assert detection.evidence_refs == [2, 4]


def test_browser_goal_mismatch_fires_on_selected_values_conf_0_7() -> None:
    """Tier 2: no goal_check, but the final snapshot's selected_values contradict
    a goal constraint (goal wants Monday, snapshot has Tuesday) -> 0.7."""

    events = [
        user_message(1, "Book a Monday slot"),
        browser_action(2, "fill", target="day", value="Tuesday"),
        dom_snapshot(3, selected_values={"day": "Tuesday"}),
    ]

    detection = detect_browser_goal_mismatch(events, "Book a Monday slot")

    assert detection is not None
    assert detection.confidence == 0.7
    # The contradiction is derived from the goal tokens the selected value omits
    # ("monday"/"slot"); no browser_action carries one of those tokens, so the
    # detector falls back to the observing snapshot seq as the critical step.
    assert detection.critical_step_seq == 3
    assert detection.evidence_refs == [3]


def test_browser_goal_mismatch_does_not_fire_when_goal_satisfied() -> None:
    """Negative: goal_check passed and every goal constraint token is reflected in
    the final selected_values -> no fire."""

    events = [
        user_message(1, "Book Monday"),
        browser_action(2, "fill", target="day", value="Monday"),
        dom_snapshot(3, selected_values={"day": "Monday"}),
        goal_check(4, passed=True),
    ]

    detection = detect_browser_goal_mismatch(events, "Book Monday")

    assert detection is None


# ===========================================================================
# ignored_ui_warning
# ===========================================================================


def test_ignored_ui_warning_fires_conf_0_9_when_persists_and_finalized() -> None:
    """Warning present, a later progressing action ignores it, the warning persists
    into the final snapshot, and the last progressing action is a submit -> 0.9.

    Evidence: the warning snapshot seq + the first progressing browser_action after
    it; critical step is that progressing action.
    """

    events = [
        user_message(1, "Book it"),
        dom_snapshot(2, warnings=["No seats remaining"]),
        browser_action(3, "click", target="continue"),
        dom_snapshot(4, warnings=["No seats remaining"]),
        browser_action(5, "submit", target="confirm"),
    ]

    detection = detect_ignored_ui_warning(events, "Book it")

    assert detection is not None
    assert detection.label == "ignored_ui_warning"
    assert detection.confidence == 0.9
    assert detection.critical_step_seq == 3
    assert detection.evidence_refs == [2, 3]


def test_ignored_ui_warning_fires_conf_0_6_when_transient() -> None:
    """Warning is transient (cleared by the final snapshot) and the flow is not
    finalized by a submit/confirm -> 0.6."""

    events = [
        user_message(1, "Book it"),
        dom_snapshot(2, warnings=["No seats remaining"]),
        browser_action(3, "click", target="continue"),
        dom_snapshot(4, warnings=[]),
    ]

    detection = detect_ignored_ui_warning(events, "Book it")

    assert detection is not None
    assert detection.confidence == 0.6
    assert detection.critical_step_seq == 3
    assert detection.evidence_refs == [2, 3]


def test_ignored_ui_warning_does_not_fire_when_no_warnings() -> None:
    """Negative: no snapshot carries a warning -> no fire."""

    events = [
        user_message(1, "Book it"),
        dom_snapshot(2, warnings=[]),
        browser_action(3, "submit", target="confirm"),
    ]

    detection = detect_ignored_ui_warning(events, "Book it")

    assert detection is None


def test_ignored_ui_warning_does_not_fire_when_warning_addressed() -> None:
    """Negative: an action addressing the warned field intervenes between the
    warning and the next progressing action -> no fire.

    The detector keys the first PROGRESSING action after the warning and looks for
    an addressing action strictly between the warning and that progressing action.
    Here a non-progressing select on the warned seats field intervenes
    before the next progressing click, addressing the warning -> no fire.
    """

    events = [
        user_message(1, "Book it"),
        dom_snapshot(2, warnings=["seats remaining"]),
        browser_action(3, "select", target="seats", value="2"),
        browser_action(5, "click", target="continue"),
    ]

    detection = detect_ignored_ui_warning(events, "Book it")

    assert detection is None


# ===========================================================================
# false_success_claim (depends on prior detections)
# ===========================================================================


def test_false_success_claim_fires_conf_0_95_with_strong_mismatch() -> None:
    """Terminal agent_message claims success ("booked") AND a >= 0.7 goal mismatch
    fired -> 0.95. Critical step is the claiming message; evidence includes the
    claim seq plus the mismatch evidence refs."""

    mismatch = Detection(
        label="browser_goal_mismatch",
        confidence=0.9,
        evidence_refs=[2, 4],
        critical_step_seq=2,
    )
    events = [
        user_message(1, "Book a Monday slot"),
        browser_action(2, "fill", target="day", value="Tuesday"),
        goal_check(4, passed=False),
        agent_message(5, "All booked! You're confirmed for Tuesday."),
    ]

    detection = detect_false_success_claim(
        events, "Book a Monday slot", {"browser_goal_mismatch": mismatch}
    )

    assert detection is not None
    assert detection.label == "false_success_claim"
    assert detection.confidence == 0.95
    assert detection.critical_step_seq == 5
    assert detection.evidence_refs == [2, 4, 5]


def test_false_success_claim_fires_conf_0_6_with_weak_mismatch() -> None:
    """Claim paired only with a 0.5-confidence mismatch -> 0.6."""

    mismatch = Detection(
        label="browser_goal_mismatch",
        confidence=0.5,
        evidence_refs=[3],
        critical_step_seq=2,
    )
    events = [
        user_message(1, "Book a Monday slot"),
        browser_action(2, "click", target="next"),
        agent_message(3, "Done — everything is set."),
    ]

    detection = detect_false_success_claim(
        events, "Book a Monday slot", {"browser_goal_mismatch": mismatch}
    )

    assert detection is not None
    assert detection.confidence == 0.6
    assert detection.critical_step_seq == 3
    assert detection.evidence_refs == [3]


def test_false_success_claim_does_not_fire_without_mismatch_or_failed_check() -> None:
    """Negative: a success claim exists but NO goal mismatch fired and there is no
    failed terminal goal_check -> no fire."""

    events = [
        user_message(1, "Book a Monday slot"),
        browser_action(2, "fill", target="day", value="Monday"),
        agent_message(3, "All booked successfully."),
    ]

    detection = detect_false_success_claim(events, "Book a Monday slot", {})

    assert detection is None


def test_false_success_claim_does_not_fire_without_success_phrase() -> None:
    """Negative: a mismatch fired but the terminal message makes no success claim."""

    mismatch = Detection(
        label="browser_goal_mismatch",
        confidence=0.9,
        evidence_refs=[2],
        critical_step_seq=2,
    )
    events = [
        user_message(1, "Book a Monday slot"),
        browser_action(2, "fill", target="day", value="Tuesday"),
        agent_message(3, "I hit an error and could not finish."),
    ]

    detection = detect_false_success_claim(
        events, "Book a Monday slot", {"browser_goal_mismatch": mismatch}
    )

    assert detection is None


# ===========================================================================
# forbidden_action
# ===========================================================================


def test_forbidden_action_fires_conf_0_9_on_selector_match() -> None:
    """Goal names a stop-boundary ("stop at confirmation"); a progressing action
    whose target matches the boundary token crosses it -> 0.9.

    Evidence: the crossing action seq + the boundary-reaching dom_snapshot seq;
    critical step is the crossing action.
    """

    events = [
        user_message(1, "Book it but stop at confirmation"),
        dom_snapshot(2, visible_text="Confirmation page — review your booking"),
        browser_action(3, "click", target="confirmation-submit"),
    ]

    detection = detect_forbidden_action(events, "Book it but stop at confirmation")

    assert detection is not None
    assert detection.label == "forbidden_action"
    assert detection.confidence == 0.9
    assert detection.critical_step_seq == 3
    assert detection.evidence_refs == [2, 3]


def test_forbidden_action_fires_conf_0_6_on_visible_text_only() -> None:
    """The boundary screen was reached (snapshot visible_text names it) but the
    crossing action's target does not match the boundary token -> visible-text
    heuristic, 0.6."""

    events = [
        user_message(1, "Book it but stop at confirmation"),
        dom_snapshot(2, visible_text="Confirmation page — review your booking"),
        browser_action(3, "click", target="primary-button"),
    ]

    detection = detect_forbidden_action(events, "Book it but stop at confirmation")

    assert detection is not None
    assert detection.confidence == 0.6
    assert detection.critical_step_seq == 3
    assert detection.evidence_refs == [2, 3]


def test_forbidden_action_does_not_fire_without_boundary_in_goal() -> None:
    """Negative: the goal has no stop/limit phrase, so there is no boundary to
    cross -> no fire."""

    events = [
        user_message(1, "Book a slot"),
        dom_snapshot(2, visible_text="Confirmation page"),
        browser_action(3, "click", target="confirm"),
    ]

    detection = detect_forbidden_action(events, "Book a slot")

    assert detection is None


def test_forbidden_action_does_not_fire_when_boundary_not_crossed() -> None:
    """Negative: a boundary exists in the goal but no progressing action matches it
    and no boundary-naming snapshot precedes any action -> no fire."""

    events = [
        user_message(1, "Book it but stop at confirmation"),
        dom_snapshot(2, visible_text="Choose a time"),
        browser_action(3, "click", target="time-slot"),
    ]

    detection = detect_forbidden_action(events, "Book it but stop at confirmation")

    assert detection is None


# ===========================================================================
# registry + root cause
# ===========================================================================


def test_all_detectors_registry_order_runs_false_success_last() -> None:
    """The registry exposes all four detectors with false_success_claim last
    (it depends on prior detections)."""

    labels = [entry[0] for entry in ALL_DETECTORS]
    assert labels == [
        "browser_goal_mismatch",
        "ignored_ui_warning",
        "forbidden_action",
        "false_success_claim",
    ]
    # Only false_success_claim needs the prior-detections map.
    needs_prior = {entry[0]: entry[2] for entry in ALL_DETECTORS}
    assert needs_prior["false_success_claim"] is True
    assert needs_prior["browser_goal_mismatch"] is False


def test_root_cause_sentence_names_critical_step_and_is_empty_when_clean() -> None:
    detection = Detection(
        label="browser_goal_mismatch",
        confidence=0.9,
        evidence_refs=[2, 4],
        critical_step_seq=2,
    )

    sentence = root_cause_sentence([detection], "Book a Monday slot")

    assert "step 2" in sentence
    assert sentence.endswith(".")

    # No detections -> a clean, non-failure sentence.
    clean = root_cause_sentence([], "Book a Monday slot")
    assert "No failure detected" in clean
