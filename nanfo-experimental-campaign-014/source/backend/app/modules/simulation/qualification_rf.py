"""Independent RF reconstruction; fitter only sees preregistered training rows."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from app.modules.autonomy.artifact_io import EvidenceError, StrictEvidence
from app.modules.simulation.calibration import CalibrationRequest, RFMeasurement, evaluate_calibration
from app.modules.simulation.qualification_protocol import ImportedCampaign, Name, Positive
from app.modules.simulation.rf import PointMeters, RFScene, rf_config_hash


class RFQualificationConfig(StrictEvidence):
    schema_version: Literal["nanfo.rf-qualification-config.v1"]
    scene: RFScene
    coordinate_units: Literal["meters"]
    coordinate_axes: Literal["local-z-up"]
    signal_units: Literal["dBm"]
    coordinate_registration_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_holdout_mae_db: Positive
    max_holdout_absolute_error_db: Positive
    min_train_samples: int = Field(ge=2, le=10000)
    min_holdout_samples: int = Field(ge=2, le=10000)


class RFReading(StrictEvidence):
    receiver_id: Name
    transmitter_id: Name
    coordinate_frame_id: Name
    receiver: PointMeters
    signal_dbm: float = Field(ge=-250, le=100)
    signal_units: Literal["dBm"]
    coordinate_units: Literal["meters"]
    coordinate_axes: Literal["local-z-up"]


def reference_prediction(scene: RFScene, receiver: PointMeters) -> float:
    """Independent segment intersection and log-distance arithmetic, no RF evaluator.

    Z is vertical for the existing RF model (spatial Y-up needs a surveyed transform).
    This deliberate reference implementation is a verification oracle, not runtime RF.
    """
    tx = (scene.transmitter.x, scene.transmitter.y, scene.transmitter.z)
    rx = (receiver.x, receiver.y, receiver.z)
    vector = tuple(b - a for a, b in zip(tx, rx, strict=True))
    distance = max(sum(v * v for v in vector) ** 0.5, scene.reference_distance_m)
    loss = 20 * math.log10(4 * math.pi * scene.reference_distance_m * scene.frequency_mhz * 1e6 / 299792458)
    loss += 10 * scene.path_loss_exponent * math.log10(distance / scene.reference_distance_m)
    defaults = {"glass": 3.0, "drywall": 4.0, "concrete": 12.0, "metal": 20.0}
    for wall in scene.walls:
        wx, wy = wall.end.x - wall.start.x, wall.end.y - wall.start.y
        # Solve the 2x2 line system using independent determinant expressions.
        det = vector[1] * wx - vector[0] * wy
        if abs(det) <= 1e-12 * math.hypot(*vector[:2]) * math.hypot(wx, wy):
            continue
        ax, ay = wall.start.x - tx[0], wall.start.y - tx[1]
        ray = (ay * wx - ax * wy) / det
        segment = (vector[0] * ay - vector[1] * ax) / det
        height = tx[2] + ray * vector[2]
        if 0 < ray < 1 and 0 <= segment <= 1 and wall.start.z <= height <= wall.start.z + wall.height_m:
            loss += defaults[wall.material] if wall.loss_db is None else wall.loss_db
    return scene.tx_power_dbm + scene.tx_gain_dbi + scene.rx_gain_dbi - loss


def qualify_rf(campaign: ImportedCampaign) -> dict:
    config = RFQualificationConfig.model_validate(campaign.configuration)
    protocol = campaign.protocol
    if protocol.domain != "rf" or config.scene.scope.network_id != protocol.network_id:
        raise EvidenceError("rf_campaign_scope_mismatch")
    native = {r.sha256 for c in campaign.captures for r in c.native_sources}
    if config.coordinate_registration_evidence_sha256 not in native:
        raise EvidenceError("coordinate_registration_evidence_missing")
    samples = {}
    groups = {r.sample_id: c.group_id for c in campaign.captures for r in c.records}
    for capture in campaign.captures:
        for record in capture.records:
            reading = RFReading.model_validate(record.measurement)
            if (reading.transmitter_id != config.scene.transmitter_id
                    or reading.coordinate_frame_id != config.scene.coordinate_frame_id):
                raise EvidenceError("rf_measurement_identity_or_frame_mismatch")
            samples[record.sample_id] = RFMeasurement(
                sample_id=record.sample_id, capture_id=groups[record.sample_id],
                source_record_id=record.source_record_id, source_id=protocol.dataset_id,
                source_kind="synthetic" if protocol.environment == "synthetic" else "measured",
                scope=config.scene.scope, config_sha256=rf_config_hash(config.scene),
                receiver_id=reading.receiver_id, receiver=reading.receiver,
                observed_at=datetime.fromtimestamp(record.observed_at_unix_seconds, timezone.utc).isoformat(),
                signal_dbm=reading.signal_dbm,
            )
    train = sorted(r.sample_id for r in campaign.records("train"))
    holdout = sorted(r.sample_id for r in campaign.records("holdout"))
    if len(train) < config.min_train_samples or len(holdout) < config.min_holdout_samples:
        raise EvidenceError("rf_sample_coverage_incomplete")
    # The existing estimator fits the offset exclusively from train_ids. Discard
    # its error report: independently reconstruct all predictions/errors below.
    fit = evaluate_calibration(CalibrationRequest(
        scene=config.scene, measurement_source_id=protocol.dataset_id,
        measurement_source_kind=samples[train[0]].source_kind,
        measurements=list(samples.values()), train_ids=train, holdout_ids=holdout,
    ))
    residuals = {key: reference_prediction(config.scene, sample.receiver) - sample.signal_dbm
                 for key, sample in samples.items()}
    reference_offset = max(-40.0, min(40.0, -math.fsum(residuals[k] for k in train) / len(train)))
    if fit.offset_db is None or not math.isclose(fit.offset_db, reference_offset, abs_tol=1e-9):
        raise EvidenceError("rf_fit_reference_disagreement")
    errors = [residuals[k] + fit.offset_db for k in holdout]
    mae = math.fsum(abs(e) for e in errors) / len(errors)
    maximum = max(abs(e) for e in errors)
    passed = mae <= config.max_holdout_mae_db and maximum <= config.max_holdout_absolute_error_db
    return {
        "schema_version": "nanfo.rf-independent-result.v1",
        "campaign_sha256": campaign.campaign_sha256,
        "protocol_sha256": campaign.protocol_sha256,
        "environment": protocol.environment,
        "offset_db": fit.offset_db, "train_count": len(train), "holdout_count": len(holdout),
        "holdout_mae_db": mae, "holdout_max_absolute_error_db": maximum,
        "holdout_rmse_db": math.sqrt(math.fsum(e * e for e in errors) / len(errors)),
        "holdout_errors_db": dict(zip(holdout, errors, strict=True)),
        "empirical_acceptance_passed": passed,
        "physical_qualified": False, "physical_safety_authorized": False,
        "limitations": ["Empirical RF accuracy is not a guaranteed physical bound or network safety authorization.",
                        "No interference/SINR/capacity qualification; nominal wall losses remain assumptions."],
    }
