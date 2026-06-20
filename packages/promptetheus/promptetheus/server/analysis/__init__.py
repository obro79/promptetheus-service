"""Analysis engine: rule detectors + incident assembly (runs inside FastAPI)."""

from __future__ import annotations

from .detectors import (
    ALL_DETECTORS,
    detect_browser_goal_mismatch,
    detect_false_success_claim,
    detect_forbidden_action,
    detect_ignored_ui_warning,
    root_cause_sentence,
)
from .engine import analyze_session, assemble_incidents

__all__ = [
    "ALL_DETECTORS",
    "analyze_session",
    "assemble_incidents",
    "detect_browser_goal_mismatch",
    "detect_false_success_claim",
    "detect_forbidden_action",
    "detect_ignored_ui_warning",
    "root_cause_sentence",
]
