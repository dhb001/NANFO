"""C17 confidence gates (constitution §2 "Safe Autonomy", ADR-028 C17).

Every persisted AI proposal carries evidence plus a typed confidence. Autonomous
dispatch additionally requires *calibrated* confidence at or above the operator's
``min_confidence`` (never below the constitution's 95 % automatic tier). Raw policy
probabilities are uncalibrated by construction; ``allow_uncalibrated_confidence`` is
honoured only in the explicitly enabled experimental lab, never in production.
"""

from __future__ import annotations

CONFIDENCE_MISSING = "confidence_missing"
PROPOSAL_EVIDENCE_MISSING = "proposal_evidence_missing"
CONFIDENCE_UNCALIBRATED = "confidence_uncalibrated"
CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"


def uncalibrated_confidence_honoured(settings=None) -> bool:
    """Only the explicitly enabled experimental lab may act on uncalibrated confidence."""
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    return (getattr(settings, "NANFO_EXPERIMENTAL_LAB_ENABLED", False) is True
            and getattr(settings, "EXECUTION_MODE", None) == "emulation")


def explainability_reasons(proposal) -> list[str]:
    """Reasons a proposal may not be persisted at all (constitution: evidence + confidence)."""
    reasons = []
    if not getattr(proposal, "evidence", None):
        reasons.append(PROPOSAL_EVIDENCE_MISSING)
    if getattr(proposal, "confidence", None) is None:
        reasons.append(CONFIDENCE_MISSING)
    return reasons


def dispatch_confidence_reasons(confidence, operational, *, honour_uncalibrated: bool) -> list[str]:
    """Refusal reasons for autonomous dispatch; an empty list means the C17 gate passes."""
    if confidence is None:
        return [CONFIDENCE_MISSING]
    reasons = []
    if not confidence.calibrated and not (honour_uncalibrated and operational.allow_uncalibrated_confidence):
        reasons.append(CONFIDENCE_UNCALIBRATED)
    if confidence.value < operational.min_confidence:
        reasons.append(CONFIDENCE_BELOW_THRESHOLD)
    return reasons
