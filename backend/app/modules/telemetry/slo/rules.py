"""Pure runtime-adapter SLO rules: window deltas, anomaly flags, rollup and trends.

All functions are deterministic and side-effect free so the persisted-window
evaluator (``evaluator.py``) and its tests can reason about exact transitions.
Counters in Redis are monotonic totals; every rule here operates on the DELTA
observed during one evaluation window, so an old failure never keeps an SLO
alert active forever.
"""

from __future__ import annotations

from typing import Any

WINDOW_COUNTERS = ("ingest_attempts", "ingest_failures", "invalid_samples", "dropped_samples")
COUNTER_SNAPSHOT_KEYS = {name: f"runtime_adapter_{name}" for name in WINDOW_COUNTERS}

INVALID_SAMPLE_RATIO_WARN_THRESHOLD = 0.25
ANOMALY_STREAK_CRITICAL_THRESHOLD = 3
TREND_WINDOW_MAX_SIZE = 10
TRANSITION_FREQUENCY_ALERT_THRESHOLD = 3
REASON_FREQUENCY_ALERT_THRESHOLD = 3
THRESHOLD_CROSS_COOLDOWN_EVALUATIONS = 3

PHASE_ENTER = "enter-cooldown"
PHASE_SUPPRESSED = "cooldown-suppressed"
PHASE_EXPIRED_REEMIT = "cooldown-expired-reemit"
PHASE_CLEARED_RECOVERY = "cooldown-cleared-recovery"
THRESHOLD_DIMENSIONS = {
    "transition_frequency": TRANSITION_FREQUENCY_ALERT_THRESHOLD,
    "reason_frequency": REASON_FREQUENCY_ALERT_THRESHOLD,
}

ALERT_GENERATED = "alert.generated"
ALERT_RESOLVED = "alert.resolved"
ALERT_KEY = "telemetry_runtime_adapter_slo_threshold_breach"
RUNBOOK_REFERENCE = "docs/project/TelemetryRuntimeAdapterRunbook.md#runtime-adapter-slo-threshold-response"
RUNBOOK_VERSION = "1.0"
PLAYBOOK_COMBINED = "runtime_adapter_slo_combined_threshold_response"
PLAYBOOK_REASON = "runtime_adapter_slo_reason_threshold_response"
PLAYBOOK_TRANSITION = "runtime_adapter_slo_transition_threshold_response"
PLAYBOOK_RECOVERY = "runtime_adapter_slo_recovery_validation"

THRESHOLDS: dict[str, float | int] = {
    "invalid_sample_ratio_warn_threshold": INVALID_SAMPLE_RATIO_WARN_THRESHOLD,
    "anomaly_streak_critical_threshold": ANOMALY_STREAK_CRITICAL_THRESHOLD,
    "transition_frequency_alert_threshold": TRANSITION_FREQUENCY_ALERT_THRESHOLD,
    "reason_frequency_alert_threshold": REASON_FREQUENCY_ALERT_THRESHOLD,
    # Historical payload key; the unit is now evaluator windows, not health reads.
    "threshold_cross_cooldown_reads": THRESHOLD_CROSS_COOLDOWN_EVALUATIONS,
}


def non_negative_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def current_counters(snapshot: dict[str, Any]) -> dict[str, int]:
    return {name: non_negative_int(snapshot.get(key, 0)) for name, key in COUNTER_SNAPSHOT_KEYS.items()}


def window_deltas(current: dict[str, int], baseline: dict[str, int] | None) -> tuple[dict[str, int], bool]:
    """Return per-window deltas and whether a counter reset was detected.

    The first window only establishes the baseline (all deltas zero): historical
    totals accumulated before the evaluator started are not attributed to it.
    A total lower than its baseline means Redis was reset; the new total is the
    best available delta for that window.
    """
    if baseline is None:
        return dict.fromkeys(WINDOW_COUNTERS, 0), False
    deltas: dict[str, int] = {}
    reset = False
    for name in WINDOW_COUNTERS:
        now, before = current.get(name, 0), non_negative_int(baseline.get(name, 0))
        if now < before:
            reset = True
            deltas[name] = now
        else:
            deltas[name] = now - before
    return deltas, reset


def invalid_sample_ratio(*, invalid_samples: int, ingest_attempts: int) -> float:
    total = invalid_samples + ingest_attempts
    return invalid_samples / total if total > 0 else 0.0


def anomaly_reason_flags(deltas: dict[str, int]) -> list[str]:
    flags = []
    if deltas.get("ingest_failures", 0) > 0:
        flags.append("ingest_failures_detected")
    if deltas.get("dropped_samples", 0) > 0:
        flags.append("dropped_samples_detected")
    ratio = invalid_sample_ratio(invalid_samples=deltas.get("invalid_samples", 0),
                                 ingest_attempts=deltas.get("ingest_attempts", 0))
    if ratio > INVALID_SAMPLE_RATIO_WARN_THRESHOLD:
        flags.append("invalid_sample_ratio_exceeded")
    return flags


def next_anomaly_streak(previous: int, flags: list[str]) -> int:
    return previous + 1 if flags else 0


def rollup_severity(*, anomaly_streak: int, sustained_failure_active: bool,
                    flags: list[str]) -> tuple[str, str]:
    if sustained_failure_active:
        return "critical", "runtime_sustained_failure_active"
    if anomaly_streak >= ANOMALY_STREAK_CRITICAL_THRESHOLD:
        return "critical", "anomaly_streak_threshold_exceeded"
    if flags or anomaly_streak > 0:
        return "degraded", "runtime_adapter_anomaly_detected"
    return "ok", "runtime_adapter_healthy"


def trend_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    transitions: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for previous, current in zip(entries, entries[1:], strict=False):
        key = f"{previous['severity']}->{current['severity']}"
        transitions[key] = transitions.get(key, 0) + 1
    for entry in entries:
        for reason in entry.get("flags", []):
            reasons[str(reason)] = reasons.get(str(reason), 0) + 1
    return {
        "window_size": len(entries),
        "max_window_size": TREND_WINDOW_MAX_SIZE,
        "severity_transition_counts": dict(sorted(transitions.items())),
        "anomaly_reason_frequency": dict(sorted(reasons.items())),
    }


def crossed_values(summary: dict[str, Any], dimension: str) -> dict[str, int]:
    source = summary["severity_transition_counts" if dimension == "transition_frequency"
                     else "anomaly_reason_frequency"]
    threshold = THRESHOLD_DIMENSIONS[dimension]
    return {key: value for key, value in sorted(source.items()) if value >= threshold}


def threshold_step(previous: dict[str, Any] | None, *, crossed: dict[str, int]) -> tuple[dict[str, Any], str]:
    """Advance one dimension's cooldown state by exactly one evaluation window."""
    previous = previous or {}
    was_initialized = bool(previous.get("initialized", False))
    was_crossed = bool(previous.get("threshold_crossed", False))
    elapsed = non_negative_int(previous.get("evaluations_since_last_crossed_emit", 0))
    if crossed:
        if not was_initialized or not was_crossed:
            return {"initialized": True, "threshold_crossed": True, "evaluations_since_last_crossed_emit": 0}, PHASE_ENTER
        elapsed += 1
        if elapsed >= THRESHOLD_CROSS_COOLDOWN_EVALUATIONS:
            return ({"initialized": True, "threshold_crossed": True, "evaluations_since_last_crossed_emit": 0},
                    PHASE_EXPIRED_REEMIT)
        return ({"initialized": True, "threshold_crossed": True, "evaluations_since_last_crossed_emit": elapsed},
                PHASE_SUPPRESSED)
    phase = PHASE_CLEARED_RECOVERY if was_initialized and was_crossed else ""
    return {"initialized": True, "threshold_crossed": False, "evaluations_since_last_crossed_emit": 0}, phase


def select_playbook(*, event_type: str, flags: list[str], severity_reason: str) -> str:
    if event_type == ALERT_RESOLVED:
        return PLAYBOOK_RECOVERY
    has_reason = bool(flags)
    has_transition = severity_reason in {"anomaly_streak_threshold_exceeded", "runtime_sustained_failure_active"}
    if has_transition and has_reason:
        return PLAYBOOK_COMBINED
    if has_transition:
        return PLAYBOOK_TRANSITION
    if has_reason:
        return PLAYBOOK_REASON
    return PLAYBOOK_COMBINED


def alert_payload(*, event_type: str, previous_active: bool, current_active: bool, severity: str,
                  severity_reason: str, flags: list[str], window: dict[str, Any]) -> dict[str, Any]:
    """Platform-scoped SLO alert payload.

    The runtime-adapter counters are process-wide (not per tenant), so the alert
    deliberately carries no ``workspace_id``/``network_id``: attributing it to
    whichever tenant ingested last would leak and misroute platform alerts.
    """
    return {
        "alert_key": ALERT_KEY,
        "alert_scope": "platform",
        "event_type": event_type,
        "severity": severity,
        "severity_reason": severity_reason,
        "runtime_adapter_slo_alert_active": current_active,
        "previous_runtime_adapter_slo_alert_active": previous_active,
        "anomaly_reason_flags": sorted(set(flags)),
        "runtime_adapter_slo_snapshot": {
            "last_batch_size": window["last_batch_size"],
            "invalid_samples": window["invalid_samples"],
            "dropped_samples": window["dropped_samples"],
            "ingest_attempts": window["ingest_attempts"],
            "ingest_failures": window["ingest_failures"],
        },
        "evaluation_window": {"start": window["start"], "end": window["end"], "seconds": window["seconds"],
                              "counter_reset": window["counter_reset"]},
        "thresholds": dict(THRESHOLDS),
        "runbook_reference": RUNBOOK_REFERENCE,
        "runbook_version": RUNBOOK_VERSION,
        "runbook_playbook": select_playbook(event_type=event_type, flags=flags, severity_reason=severity_reason),
        "observed_at": window["end"],
    }
