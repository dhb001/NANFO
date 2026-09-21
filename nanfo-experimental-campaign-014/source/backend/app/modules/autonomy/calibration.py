"""ADR-013 empirical diagnostics, explicitly not a TrustedCalibration factory."""

from __future__ import annotations

import hashlib
from fractions import Fraction
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.autonomy.artifact_io import (
    SHA256,
    ArtifactRef,
    ArtifactStore,
    EvidenceError,
    StrictEvidence,
    parse_json,
)
from app.modules.autonomy.safety import _upper_float

Amount = Annotated[float, Field(ge=0, le=1e15)]
Seconds = Annotated[float, Field(gt=0, le=3600)]
Name = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^\S+$")]
Seed = Annotated[int, Field(ge=1000, le=1999)]


class CalibrationPlan(StrictEvidence):
    schema_version: Literal["nanfo.calibration-plan.v1"]
    spec_sha256: SHA256
    contract_sha256: SHA256
    declared_at_unix_seconds: Amount
    fit_seeds: list[Seed] = Field(min_length=1, max_length=500)
    holdout_seeds: list[Seed] = Field(min_length=1, max_length=500)
    egress_ids: list[Name] = Field(min_length=1, max_length=256)
    action_ids: list[Name] = Field(min_length=1, max_length=256)
    min_samples_per_group: int = Field(ge=2, le=10000)
    queue_threshold_bytes: Annotated[float, Field(gt=0, le=1e15)]
    dt_seconds: Seconds

    @model_validator(mode="after")
    def unique(self):
        for values in (
            self.fit_seeds,
            self.holdout_seeds,
            self.egress_ids,
            self.action_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate calibration scope")
        if set(self.fit_seeds) & set(self.holdout_seeds):
            raise ValueError("fit/holdout leakage")
        return self


class QueueTransition(StrictEvidence):
    """Endpoint bytes and same-window counters, not path peaks or utilization.

    Measurements must already be exported by an operator-reviewed collector.
    Counter differences are empirical interval averages, not service guarantees.
    """

    sample_id: Name
    episode_id: Name
    seed: Seed
    action_id: Name
    egress_id: Name
    start_unix_seconds: Amount
    end_unix_seconds: Amount
    queue_before_bytes: Amount
    queue_after_bytes: Amount
    arrival_counter_before_bytes: Annotated[int, Field(ge=0, le=2**63 - 1)]
    arrival_counter_after_bytes: Annotated[int, Field(ge=0, le=2**63 - 1)]
    service_counter_before_bytes: Annotated[int, Field(ge=0, le=2**63 - 1)]
    service_counter_after_bytes: Annotated[int, Field(ge=0, le=2**63 - 1)]
    measurement_complete: Literal[True]
    attribution_complete: Literal[True]
    stationary: Literal[True]
    counter_reset: Literal[False]
    raw_evidence: ArtifactRef

    @model_validator(mode="before")
    @classmethod
    def exact_flags(cls, value):
        if isinstance(value, dict):
            for key in (
                "measurement_complete",
                "attribution_complete",
                "stationary",
                "counter_reset",
            ):
                if type(value.get(key)) is not bool:
                    raise ValueError("measurement flags must be booleans")
        return value

    @model_validator(mode="after")
    def interval(self):
        if not 0 < self.end_unix_seconds - self.start_unix_seconds <= 3600:
            raise ValueError("invalid measurement interval")
        if (
            self.arrival_counter_after_bytes < self.arrival_counter_before_bytes
            or self.service_counter_after_bytes < self.service_counter_before_bytes
        ):
            raise ValueError("counter reset")
        return self


class MeasuredTraces(StrictEvidence):
    schema_version: Literal["nanfo.matched-queue-traces.v1"]
    provenance: Literal["measured-lab"]
    dataplane: Literal["linux-frr"]
    spec_sha256: SHA256
    contract_sha256: SHA256
    plan_sha256: SHA256
    samples: list[QueueTransition] = Field(min_length=4, max_length=10000)


class CalibrationInput(StrictEvidence):
    schema_version: Literal["nanfo.calibration-input.v1"]
    plan: ArtifactRef
    traces: ArtifactRef


def universal_queue_bound(
    *,
    queue_bytes: float,
    arrival_upper_bytes_per_second: float,
    dt_seconds: float,
    error_upper_bytes: float = 0.0,
):
    """Conditional no-service bound. The arrival cap itself still needs justification."""
    for value in (queue_bytes, arrival_upper_bytes_per_second, error_upper_bytes):
        if isinstance(value, bool) or not 0 <= value <= 1e15:
            raise EvidenceError("invalid_universal_bound_input")
    if isinstance(dt_seconds, bool) or not 0 < dt_seconds <= 3600:
        raise EvidenceError("invalid_universal_bound_horizon")
    q = Fraction(queue_bytes)
    increment = Fraction(arrival_upper_bytes_per_second) * Fraction(
        dt_seconds
    ) + Fraction(error_upper_bytes)
    upper = q + increment
    drift = q * increment + increment * increment / 2
    return {
        "q_next_upper_bytes": _upper_float(upper),
        "drift_upper_bytes_squared": _upper_float(drift),
        "zero_budget_satisfied": drift <= 0,
        "service_lower_bytes_per_second": 0.0,
    }


def calibrate(plan: CalibrationPlan, traces: MeasuredTraces) -> dict:
    """Fit on predeclared train seeds only; never widen after holdout failures."""
    if (plan.spec_sha256, plan.contract_sha256) != (
        traces.spec_sha256,
        traces.contract_sha256,
    ):
        raise EvidenceError("calibration_contract_mismatch")
    ids, episodes, groups = set(), {}, {}
    expected = {
        (egress, action) for egress in plan.egress_ids for action in plan.action_ids
    }
    seen_seeds = set()
    for sample in traces.samples:
        if sample.sample_id in ids:
            raise EvidenceError("duplicate_calibration_sample")
        ids.add(sample.sample_id)
        seed = episodes.setdefault(sample.episode_id, sample.seed)
        if seed != sample.seed:
            raise EvidenceError("calibration_episode_split_leakage")
        seen_seeds.add(sample.seed)
        if sample.seed not in {*plan.fit_seeds, *plan.holdout_seeds}:
            raise EvidenceError("calibration_seed_not_predeclared")
        if sample.start_unix_seconds <= plan.declared_at_unix_seconds:
            raise EvidenceError("calibration_plan_not_predeclared")
        dt = Fraction(sample.end_unix_seconds) - Fraction(sample.start_unix_seconds)
        if dt != Fraction(plan.dt_seconds):
            raise EvidenceError("calibration_horizon_mismatch")
        group = (sample.egress_id, sample.action_id)
        if group not in expected:
            raise EvidenceError("calibration_scope_mismatch")
        split = "fit" if sample.seed in plan.fit_seeds else "holdout"
        groups.setdefault((group, split), []).append(sample)
    if seen_seeds != {*plan.fit_seeds, *plan.holdout_seeds}:
        raise EvidenceError("calibration_seed_coverage_incomplete")
    # Do not count overlapping/repeated windows as independent evidence.
    windows = {}
    for sample in traces.samples:
        key = sample.episode_id, sample.egress_id
        windows.setdefault(key, []).append(
            (sample.start_unix_seconds, sample.end_unix_seconds)
        )
    for intervals in windows.values():
        ordered = sorted(intervals)
        if any(right[0] < left[1] for left, right in pairwise(ordered)):
            raise EvidenceError("calibration_windows_overlap")
    diagnostics, reasons = (
        [],
        [
            "causal_arrival_service_guarantees_missing",
            "trusted_calibration_not_installed",
            "normalized_measurement_derivation_unverified",
        ],
    )
    for group in sorted(expected):
        fit = groups.get((group, "fit"), [])
        holdout = groups.get((group, "holdout"), [])
        if min(len(fit), len(holdout)) < plan.min_samples_per_group:
            raise EvidenceError("calibration_group_coverage_incomplete")
        dt = Fraction(plan.dt_seconds)
        arrival = max(
            Fraction(s.arrival_counter_after_bytes - s.arrival_counter_before_bytes)
            / dt
            for s in fit
        )
        service = min(
            Fraction(s.service_counter_after_bytes - s.service_counter_before_bytes)
            / dt
            for s in fit
        )

        def predicted(sample, arrival=arrival, service=service, dt=dt):
            return max(
                Fraction(0),
                Fraction(sample.queue_before_bytes) + (arrival - service) * dt,
            )

        error = max(
            Fraction(0), max(Fraction(s.queue_after_bytes) - predicted(s) for s in fit)
        )
        failures = {
            "arrival": [],
            "service": [],
            "queue": [],
            "drift": [],
            "envelope": [],
        }
        worst_drift = None
        for sample in holdout:
            upper = predicted(sample) + error
            drift = (upper * upper - Fraction(sample.queue_before_bytes) ** 2) / 2
            worst_drift = drift if worst_drift is None else max(worst_drift, drift)
            checks = {
                "arrival": Fraction(
                    sample.arrival_counter_after_bytes
                    - sample.arrival_counter_before_bytes
                )
                > arrival * dt,
                "service": Fraction(
                    sample.service_counter_after_bytes
                    - sample.service_counter_before_bytes
                )
                < service * dt,
                "queue": Fraction(sample.queue_after_bytes) > upper,
                "drift": drift > 0,
                "envelope": max(upper, Fraction(sample.queue_before_bytes))
                > Fraction(plan.queue_threshold_bytes),
            }
            for name, failed in checks.items():
                if failed:
                    failures[name].append(sample.sample_id)
        if any(failures[name] for name in ("arrival", "service", "queue")):
            reasons.append("empirical_holdout_coverage_failed")
        if failures["drift"]:
            reasons.append("empirical_drift_budget_exceeded")
        if failures["envelope"]:
            reasons.append("empirical_queue_envelope_exceeded")
        diagnostics.append(
            {
                "egress_id": group[0],
                "action_id": group[1],
                "fit_samples": len(fit),
                "holdout_samples": len(holdout),
                "arrival_fitted_max_bytes_per_second": _upper_float(arrival),
                "service_fitted_min_bytes_per_second": -_upper_float(-service),
                "error_fitted_max_bytes": _upper_float(error),
                "failure_sample_ids": failures,
                "holdout_queue_coverage": 1 - len(failures["queue"]) / len(holdout),
                "worst_holdout_drift_bytes_squared": _upper_float(worst_drift),
                "universal_no_service_at_max_holdout_queue": universal_queue_bound(
                    queue_bytes=max(s.queue_before_bytes for s in holdout),
                    arrival_upper_bytes_per_second=_upper_float(arrival),
                    dt_seconds=plan.dt_seconds,
                    error_upper_bytes=_upper_float(error),
                ),
            }
        )
    return {
        "schema_version": "nanfo.calibration-diagnostics.v1",
        "qualified": False,
        "trusted_calibration": None,
        "spec_sha256": traces.spec_sha256,
        "contract_sha256": traces.contract_sha256,
        "reasons": list(dict.fromkeys(reasons)),
        "groups": diagnostics,
        "limitations": [
            "Fitted extrema are not causal guarantees.",
            "Interval-average service can be unused before late arrivals.",
            "No counterfactual, transition-delay or unavailable-service guarantee.",
        ],
    }


def assess_calibration(store: ArtifactStore, path: str) -> dict:
    document = store.document(path)
    if (
        isinstance(document, dict)
        and type(document.get("version")) is int
        and document["version"] == 3
    ):
        from app.modules.autonomy.qualification import import_qualification

        assessment = import_qualification(store, path)
        return {
            **assessment["calibration"],
            "spec_sha256": assessment["spec_sha256"],
            "contract_sha256": assessment["contract_sha256"],
            "qualification_manifest_sha256": assessment["manifest_sha256"],
        }
    inputs = CalibrationInput.model_validate(document)
    plan_bytes = store.referenced(inputs.plan)
    plan = CalibrationPlan.model_validate(parse_json(plan_bytes))
    traces = MeasuredTraces.model_validate(parse_json(store.referenced(inputs.traces)))
    if traces.plan_sha256 != hashlib.sha256(plan_bytes).hexdigest():
        raise EvidenceError("calibration_plan_hash_mismatch")
    # Every source must be present and byte-bound. Hashes alone are not measurement authenticity.
    refs = {sample.raw_evidence.path: sample.raw_evidence for sample in traces.samples}
    if len(refs) > 256:
        raise EvidenceError("calibration_source_count_exceeded")
    if sum(ref.size_bytes for ref in refs.values()) > 64 * 1024 * 1024:
        raise EvidenceError("calibration_source_bytes_exceeded")
    for sample in traces.samples:
        if refs[sample.raw_evidence.path] != sample.raw_evidence:
            raise EvidenceError("calibration_source_identity_conflict")
    for ref in refs.values():
        store.referenced(ref)
    result = calibrate(plan, traces)
    result["inputs"] = inputs.model_dump(mode="json")
    return result
