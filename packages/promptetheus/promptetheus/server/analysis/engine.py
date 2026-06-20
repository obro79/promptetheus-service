"""Analysis engine: run detectors over a session, aggregate, and cluster incidents.

The engine is the orchestration layer above the pure detectors in detectors.py.
It runs every detector in ALL_DETECTORS over a session's ordered events, folds
the fired Detection verdicts into a single AnalysisResult, and clusters
those verdicts into deterministic incident rows persisted through the Store.

It is dependency-light by design: detectors are pure functions (no I/O), and all
persistence flows through the Store protocol. The engine never performs HTTP.
"""

from __future__ import annotations

from typing import Any

from promptetheus.server.models import AnalysisResult, Detection
from promptetheus.server.store import Store

from .detectors import (
    detect_browser_goal_mismatch,
    detect_false_success_claim,
    detect_forbidden_action,
    detect_ignored_ui_warning,
    root_cause_sentence,
)
from .classifier import (
    CANNED_ANALYSIS_ROOT_CAUSE,
    analysis_fallback_forced,
    resolve_classifier,
)

__all__ = ["analyze_session", "assemble_incidents"]


def analyze_session(
    session: dict[str, Any], events: list[dict[str, Any]]
) -> AnalysisResult:
    """Run all detectors over a session and aggregate them into an AnalysisResult.

    Detectors run in a fixed order so the result is deterministic. false_success_claim
    depends on the verdicts of the other detectors, so it runs last and receives a
    {label: Detection} map of what fired before it.

    Aggregation (per the internal contract, section 2):

    - session-level critical_step_seq = the minimum critical_step_seq across
      fired detections (None if nothing fired or no detection carried one).
    - confidence = the maximum detection confidence (0.0 if none fired).
    - root_cause = root_cause_sentence(detections, user_goal) when something
      fired, else None.
    """

    user_goal = str(session.get("user_goal") or "")

    detections: list[Detection] = []
    prior: dict[str, Detection] = {}

    # Run the independent detectors first, recording each verdict for the
    # dependent detector. Order is fixed for determinism.
    for detector in (
        detect_browser_goal_mismatch,
        detect_ignored_ui_warning,
        detect_forbidden_action,
    ):
        detection = detector(events, user_goal)
        if detection is not None:
            detections.append(detection)
            prior[detection.label] = detection

    # false_success_claim depends on what fired before it.
    false_success = detect_false_success_claim(events, user_goal, prior)
    if false_success is not None:
        detections.append(false_success)
        prior[false_success.label] = false_success

    session_id = str(session.get("id") or session.get("session_id") or "")

    if not detections:
        return AnalysisResult(session_id=session_id)

    critical_steps = [
        detection.critical_step_seq
        for detection in detections
        if detection.critical_step_seq is not None
    ]
    critical_step_seq = min(critical_steps) if critical_steps else None
    confidence = max(detection.confidence for detection in detections)
    root_cause = root_cause_sentence(detections, user_goal)

    fallback = analysis_fallback_forced()
    if fallback:
        root_cause = CANNED_ANALYSIS_ROOT_CAUSE
    else:
        refined = resolve_classifier().classify(
            user_goal=user_goal,
            detections=detections,
            root_cause=root_cause,
        )
        if refined is not None:
            root_cause = refined

    return AnalysisResult(
        session_id=session_id,
        detections=detections,
        critical_step_seq=critical_step_seq,
        confidence=confidence,
        root_cause=root_cause,
        fallback=fallback,
    )


def assemble_incidents(
    store: Store, session: dict[str, Any], result: AnalysisResult
) -> list[dict[str, Any]]:
    """Cluster a session's fired labels into deterministic incident rows and upsert them.

    One incident is created/updated per fired label. Incident identity is per
    (workspace_id, label): id = f"incident_{workspace_id}_{label}" — so the
    same failure label across sessions deterministically lands in one incident.

    Each incident row carries:

    - id — deterministic incident_{workspace_id}_{label}.
    - workspace_id / project_id — copied from the session.
    - label — the fired detector label.
    - severity — "high" if the running max confidence >= 0.9 else "medium".
    - status — "new" when first created, preserved if already set.
    - representative_session_id — set to this session when first created, preserved after.
    - owner_id — None (preserved if already assigned).
    - session_ids — deduped list of contributing session ids (order preserved).
    - critical_step_seq — the lowest critical step seen for this label.
    - confidence — the max confidence seen for this label.

    Returns the upserted incident rows (one per fired label that this session contributed to).
    """

    if not result.detections:
        return []

    workspace_id = str(session.get("workspace_id") or "")
    project_id = session.get("project_id")
    session_id = str(
        session.get("id") or session.get("session_id") or result.session_id or ""
    )

    upserted: list[dict[str, Any]] = []

    for detection in result.detections:
        label = detection.label
        incident_id = f"incident_{workspace_id}_{label}"

        existing = store.get_incident(incident_id) or {}

        # session_ids: append this session, dedupe, preserve order.
        session_ids: list[str] = [str(sid) for sid in existing.get("session_ids", [])]
        if session_id and session_id not in session_ids:
            session_ids.append(session_id)

        # confidence: max seen for this label across contributing sessions.
        existing_confidence = float(existing.get("confidence") or 0.0)
        confidence = max(existing_confidence, detection.confidence)

        # critical_step_seq: lowest seen for this label.
        critical_step_seq = detection.critical_step_seq
        existing_critical = existing.get("critical_step_seq")
        if existing_critical is not None:
            if critical_step_seq is None:
                critical_step_seq = existing_critical
            else:
                critical_step_seq = min(critical_step_seq, existing_critical)

        severity = "high" if confidence >= 0.9 else "medium"

        # status: preserve an existing status, default "new" on first creation.
        status = existing.get("status") or "new"

        representative_session_id = (
            existing.get("representative_session_id") or session_id
        )
        owner_id = existing.get("owner_id")

        incident = {
            "id": incident_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "label": label,
            "severity": severity,
            "status": status,
            "representative_session_id": representative_session_id,
            "owner_id": owner_id,
            "session_ids": session_ids,
            "critical_step_seq": critical_step_seq,
            "confidence": confidence,
        }

        upserted.append(store.upsert_incident(incident))

    return upserted
