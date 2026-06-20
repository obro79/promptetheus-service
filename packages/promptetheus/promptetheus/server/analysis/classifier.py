"""Optional LLM root-cause classifier (State-0 ships NoOp only)."""

from __future__ import annotations

import os
from typing import Any, Protocol

from promptetheus.server.models import Detection


class LLMClassifier(Protocol):
    """Refine root_cause text without changing detector labels or confidence."""

    def classify(
        self,
        *,
        user_goal: str,
        detections: list[Detection],
        root_cause: str | None,
    ) -> str | None: ...


class NoOpClassifier:
    """Returns root_cause unchanged; never mutates labels or confidence."""

    def classify(
        self,
        *,
        user_goal: str,
        detections: list[Detection],
        root_cause: str | None,
    ) -> str | None:
        return root_cause


def analysis_llm_enabled() -> bool:
    raw = os.environ.get("PROMPTETHEUS_ANALYSIS_LLM", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def analysis_fallback_forced() -> bool:
    raw = os.environ.get("PROMPTETHEUS_ANALYSIS_FALLBACK", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def resolve_classifier() -> LLMClassifier:
    if analysis_llm_enabled():
        # Hosted builds swap in a real provider-backed classifier in P15.
        return NoOpClassifier()
    return NoOpClassifier()


CANNED_ANALYSIS_ROOT_CAUSE = (
    "Deterministic fallback analysis: review the critical browser step and goal check."
)

__all__ = [
    "CANNED_ANALYSIS_ROOT_CAUSE",
    "LLMClassifier",
    "NoOpClassifier",
    "analysis_fallback_forced",
    "analysis_llm_enabled",
    "resolve_classifier",
]
