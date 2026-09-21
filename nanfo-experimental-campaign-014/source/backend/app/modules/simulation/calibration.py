"""Declared-split RF bias fitting and held-out errors; no automatic data selection."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from app.modules.simulation.evaluator import digest
from app.modules.simulation.rf import (
    PointMeters,
    RFRequest,
    RFScene,
    Scope,
    canonical_scene,
    evaluate_rf,
    rf_config_hash,
)
from app.modules.simulation.schemas import Digest, Identifier, StrictModel

CALIBRATION_VERSION = "rf-declared-split-bias.v1"


class RFMeasurement(StrictModel):
    sample_id: Identifier
    # Entire correlated capture groups must be on one side of the split.
    capture_id: Identifier
    source_record_id: Identifier
    source_id: Identifier
    source_kind: Literal["measured", "synthetic"]
    scope: Scope
    config_sha256: Digest
    receiver_id: Identifier
    receiver: PointMeters
    observed_at: Annotated[str, Field(min_length=20, max_length=40)]
    signal_dbm: Annotated[float, Field(ge=-250, le=100, allow_inf_nan=False)]

    @field_validator("observed_at")
    @classmethod
    def aware_timestamp(cls, value: str) -> str:
        if datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("Measurement requires a timezone-aware timestamp")
        return value


class CalibrationRequest(StrictModel):
    version: Literal["rf-declared-split-bias.v1"] = CALIBRATION_VERSION
    scene: RFScene
    measurement_source_id: Identifier
    measurement_source_kind: Literal["measured", "synthetic"]
    measurements: Annotated[list[RFMeasurement], Field(max_length=1024)]
    train_ids: Annotated[list[Identifier], Field(max_length=1024)]
    holdout_ids: Annotated[list[Identifier], Field(max_length=1024)]

    @model_validator(mode="after")
    def declared_matching_split(self) -> Self:
        samples = {sample.sample_id: sample for sample in self.measurements}
        train, holdout = set(self.train_ids), set(self.holdout_ids)
        if (
            len(samples) != len(self.measurements)
            or len(train) != len(self.train_ids)
            or len(holdout) != len(self.holdout_ids)
            or train & holdout
            or train | holdout != set(samples)
        ):
            raise ValueError(
                "Declare every unique sample exactly once in disjoint train/holdout sets"
            )
        config_hash = rf_config_hash(self.scene)
        records = set()
        observations = set()
        for sample in self.measurements:
            if (
                sample.scope != self.scene.scope
                or sample.config_sha256 != config_hash
                or sample.source_id != self.measurement_source_id
                or sample.source_kind != self.measurement_source_kind
            ):
                raise ValueError("Measurement scope/config/source mismatch")
            observation = (
                sample.receiver_id,
                datetime.fromisoformat(sample.observed_at),
            )
            if sample.source_record_id in records or observation in observations:
                raise ValueError("Duplicate source record or receiver observation")
            records.add(sample.source_record_id)
            observations.add(observation)
        if {samples[key].capture_id for key in train} & {
            samples[key].capture_id for key in holdout
        }:
            raise ValueError("Capture groups must not cross the train/holdout boundary")
        return self


class ErrorMetrics(StrictModel):
    count: int
    mae_db: float
    rmse_db: float
    bias_db: float
    max_absolute_error_db: float


class SplitMetrics(StrictModel):
    baseline: ErrorMetrics
    fitted: ErrorMetrics


class CalibrationResult(StrictModel):
    version: Literal["rf-declared-split-bias.v1"] = CALIBRATION_VERSION
    status: Literal["unavailable", "synthetic_only", "measured_holdout_evaluated"]
    reason: str
    calibrated: Literal[False] = False
    physical_safety_authorized: Literal[False] = False
    scope: Scope
    config_sha256: Digest
    input_sha256: Digest
    measurement_source_id: Identifier
    measurement_source_kind: Literal["measured", "synthetic"]
    train_ids: list[Identifier]
    holdout_ids: list[Identifier]
    offset_db: float | None
    offset_bound_hit: bool
    train: SplitMetrics | None
    holdout: SplitMetrics | None


def _errors(residuals: list[float]) -> ErrorMetrics:
    count = len(residuals)
    return ErrorMetrics(
        count=count,
        mae_db=math.fsum(abs(value) for value in residuals) / count,
        rmse_db=math.sqrt(math.fsum(value * value for value in residuals) / count),
        bias_db=math.fsum(residuals) / count,
        max_absolute_error_db=max(abs(value) for value in residuals),
    )


def evaluate_calibration(request: CalibrationRequest) -> CalibrationResult:
    request = CalibrationRequest.model_validate(request.model_dump())
    canonical = request.model_dump(mode="json")
    canonical["scene"] = canonical_scene(request.scene)
    canonical["measurements"].sort(key=lambda sample: sample["sample_id"])
    canonical["train_ids"] = sorted(request.train_ids)
    canonical["holdout_ids"] = sorted(request.holdout_ids)
    provenance = dict(
        scope=request.scene.scope,
        config_sha256=rf_config_hash(request.scene),
        input_sha256=digest(canonical),
        measurement_source_id=request.measurement_source_id,
        measurement_source_kind=request.measurement_source_kind,
        train_ids=sorted(request.train_ids),
        holdout_ids=sorted(request.holdout_ids),
    )
    if not request.train_ids or not request.holdout_ids:
        return CalibrationResult(
            **provenance,
            status="unavailable",
            reason="Both a declared training set and independent held-out set are required",
            offset_db=None,
            offset_bound_hit=False,
            train=None,
            holdout=None,
        )
    samples = {sample.sample_id: sample for sample in request.measurements}

    def residuals(ids: list[str]) -> list[float]:
        return [
            evaluate_rf(
                RFRequest(
                    scene=request.scene,
                    receiver_id=samples[key].receiver_id,
                    receiver=samples[key].receiver,
                )
            ).signal_dbm
            - samples[key].signal_dbm
            for key in sorted(ids)
        ]

    train = residuals(request.train_ids)
    # Only declared train residuals enter the constrained least-squares estimator.
    unconstrained = -math.fsum(train) / len(train)
    offset = max(-40.0, min(40.0, unconstrained))
    holdout = residuals(request.holdout_ids)

    def metrics(values: list[float]) -> SplitMetrics:
        return SplitMetrics(
            baseline=_errors(values),
            fitted=_errors([value + offset for value in values]),
        )

    measured = request.measurement_source_kind == "measured"
    return CalibrationResult(
        **provenance,
        status="measured_holdout_evaluated" if measured else "synthetic_only",
        reason="Declared-source errors only; no independent source attestation or acceptance threshold",
        offset_db=offset,
        offset_bound_hit=abs(unconstrained) >= 40,
        train=metrics(train),
        holdout=metrics(holdout),
    )
