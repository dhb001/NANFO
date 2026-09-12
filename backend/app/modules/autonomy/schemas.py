"""Concrete ADR-012 REST and provider contracts; no experiment vector fabrication."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.modules.autonomy.safety import (
    DemandRoute,
    SafetyAction,
    SafetyObservation,
    SafetyPolicy,
    SafetyState,
    TrustedCalibration,
)

Mode = Literal["monitor", "recommend", "autonomous"]
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
DecisionStatus = Literal[
    "observing", "observed", "blocked", "recommended", "accepted", "verified",
    "uncertain", "cancelled", "failed", "control_changed", "stopped",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, allow_inf_nan=False,
                              revalidate_instances="always")


class SetAutonomyRequest(Contract):
    network_id: uuid.UUID
    expected_revision: int = Field(strict=True, ge=0)
    mode: Mode
    checkpoint_sha256: SHA256 | None = None
    approval_expires_at: AwareDatetime | None = None

    @field_validator("approval_expires_at")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value else None


class StopAutonomyRequest(Contract):
    network_id: uuid.UUID


class OperationalSettings(Contract):
    max_observation_age_seconds: int = Field(default=30, strict=True, ge=1, le=30)
    decision_interval_seconds: int = Field(default=10, strict=True, ge=1, le=3600)
    min_route_hold_seconds: int = Field(default=3, strict=True, ge=3, le=3600)
    max_changes_per_minute: int = Field(default=10, strict=True, ge=1, le=10)


class TrainingSettings(Contract):
    reward_weights: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")],
                         Annotated[float, Field(strict=True, ge=-100, le=100, allow_inf_nan=False)]] = Field(
                             default_factory=dict, max_length=32)


class SetConfigurationRequest(Contract):
    network_id: uuid.UUID
    expected_revision: int = Field(strict=True, ge=0)
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    operational: OperationalSettings
    training: TrainingSettings


class ConfigurationRevisionResponse(Contract):
    revision: int
    actor_id: str
    reason: str
    operational: OperationalSettings
    training: TrainingSettings
    content_sha256: SHA256
    created_at: AwareDatetime


class ConfigurationResponse(Contract):
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    revision: int
    control_revision: int
    operational: OperationalSettings
    requested_training: TrainingSettings
    effective_training: TrainingSettings | None = None
    training_status: Literal["not_requested", "retraining_required"]
    effective_training_status: Literal["model_owned_unavailable"] = "model_owned_unavailable"
    safety_merge: Literal["stricter_than_calibrated_policy"] = "stricter_than_calibrated_policy"
    history: list[ConfigurationRevisionResponse]
    history_limit: int = 100


class CreateOverrideRequest(Contract):
    network_id: uuid.UUID
    intent_id: uuid.UUID
    execution_id: uuid.UUID
    expected_revision: int = Field(strict=True, ge=0)
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    duration_seconds: int = Field(strict=True, ge=1, le=3600)
    return_mode: Mode


class ReturnOverrideRequest(Contract):
    expected_revision: int = Field(strict=True, ge=0)
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class OverrideResponse(Contract):
    override_id: uuid.UUID
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    intent_id: uuid.UUID
    execution_id: uuid.UUID
    actor_id: str
    reason: str
    duration_seconds: int
    return_mode: Mode
    prior_mode: Mode
    prior_revision: int
    hold_revision: int
    checkpoint_sha256: SHA256 | None
    prior_approval_expires_at: AwareDatetime | None
    prior_approved_by_user_id: str | None
    command_sha256: SHA256
    plan_hash: SHA256
    binding_digest: SHA256
    run_id: uuid.UUID
    configuration_verified_at: AwareDatetime
    evidence_scope: Literal["historical_configuration_readback"] = "historical_configuration_readback"
    status: Literal["holding", "restoring", "restored", "return_blocked", "returned"]
    reasons: list[str]
    cancellation_id: uuid.UUID | None
    cancellation_requested_at: AwareDatetime | None
    cancelled_by_user_id: str | None
    restoration_attempts: int
    verification: dict | None
    restored_at: AwareDatetime | None
    return_requested_at: AwareDatetime | None
    return_requested_by_user_id: str | None
    return_reason: str | None
    returned_at: AwareDatetime | None
    expires_at: AwareDatetime
    created_at: AwareDatetime
    updated_at: AwareDatetime


class OverrideListResponse(Contract):
    network_id: uuid.UUID
    control_revision: int
    overrides: list[OverrideResponse]
    history_limit: int = 100


class ProviderStatus(Contract):
    provider_id: str
    status: Literal["ready", "unavailable", "incompatible", "uncalibrated"]
    reasons: list[str] = Field(default_factory=list, max_length=32)


class ProviderStatuses(Contract):
    observer: ProviderStatus
    qualification: ProviderStatus
    inference: ProviderStatus
    safety: ProviderStatus
    executor: ProviderStatus


class ObservationSample(Contract):
    record_id: uuid.UUID
    device_id: uuid.UUID
    metric: str
    value: float
    unit: str | None
    observed_at: AwareDatetime
    source: str
    run_id: str | None
    port_no: str | None


class Observation(Contract):
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    provider_id: str
    contract: str
    observed_at: AwareDatetime | None
    collected_at: AwareDatetime
    age_seconds: float | None
    fresh: bool
    compatible: bool
    reasons: list[str] = Field(default_factory=list, max_length=32)
    samples: list[ObservationSample] = Field(default_factory=list, max_length=100)
    evidence: list[str] = Field(default_factory=list, max_length=100)


class Proposal(Contract):
    action_id: str = Field(min_length=1, max_length=128)
    checkpoint_sha256: SHA256
    observation_contract: str
    evidence: list[str] = Field(min_length=1, max_length=100)


class SafetyAssessment(Contract):
    admissible: bool
    action_id: str | None = None
    model_version: str
    reasons: list[str] = Field(default_factory=list, max_length=32)
    evidence: list[str] = Field(default_factory=list, max_length=100)
    selected_action: SafetyAction | None = None
    certificate: SafetyCertificate | None = None
    binding: SafetyBinding | None = None


class SafetyDrift(Contract):
    v_before_bytes_squared: float
    v_next_upper_bytes_squared: float
    upper_bytes_squared: float
    budget_bytes_squared: float


class SafetyEnvelope(Contract):
    threshold_bytes: float
    q_next_upper_bytes: dict[str, float]


class SafetyCertificate(Contract):
    model: Literal["bounded-fluid-v1"]
    calibration_id: str
    provider_id: str
    policy_version: str
    input_sha256: SHA256
    network_id: str
    run_id: str
    snapshot_id: str
    action_id: str
    routes: list[DemandRoute]
    conditional: Literal[True]
    observed_at_unix_seconds: float
    horizon_end_unix_seconds: float
    dt_seconds: float
    actuation_delay_upper_seconds: float
    expires_at_unix_seconds: float
    drift: SafetyDrift
    envelope: SafetyEnvelope
    model_checks_passed: bool


class SafetyBinding(Contract):
    workspace_id: uuid.UUID
    observation_sha256: SHA256
    proposal_sha256: SHA256
    calibration_sha256: SHA256
    selected_action_sha256: SHA256
    evaluated_at_unix_seconds: float
    observation: SafetyObservation
    policy: SafetyPolicy
    calibration: TrustedCalibration
    state: SafetyState


def canonical_json(value) -> str:
    return json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)


def contract_digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class Qualification(Contract):
    qualified: bool
    checkpoint_sha256: SHA256 | None = None
    observation_contract: str | None = None
    manifest_sha256: SHA256 | None = None
    evidence: list[str] = Field(default_factory=list, max_length=100)
    reasons: list[str] = Field(default_factory=list, max_length=32)


class ExecutionAuthorization(Contract):
    model_config = ConfigDict(frozen=True)
    decision_id: uuid.UUID
    execution_id: uuid.UUID
    intent_id: uuid.UUID
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    actor_id: str
    checkpoint_sha256: SHA256
    approval_expires_at: AwareDatetime
    control_revision: int
    claim_token: uuid.UUID
    # Canonical JSON strings are deeply immutable, unlike frozen nested lists/dicts.
    safety_evidence_json: str
    selected_action_json: str
    safety_sha256: SHA256
    selected_action_sha256: SHA256
    certificate_expires_at_unix_seconds: float


class ExecutionReference(Contract):
    """Server-created exact owned identity, never an HTTP request capability."""
    model_config = ConfigDict(frozen=True)
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    intent_id: uuid.UUID
    execution_id: uuid.UUID
    decision_id: uuid.UUID
    control_revision: int
    claim_token: uuid.UUID


class Verification(Contract):
    execution_id: uuid.UUID
    status: Literal["pending", "verified", "cancelled", "failed", "uncertain"]
    safe_to_release: bool = False
    evidence: list[str] = Field(default_factory=list, max_length=100)
    reasons: list[str] = Field(default_factory=list, max_length=32)


class DecisionResponse(Contract):
    decision_id: uuid.UUID
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    actor_id: str
    mode: Mode
    control_revision: int
    status: DecisionStatus
    reasons: list[str]
    checkpoint_sha256: SHA256 | None
    observation: Observation | None
    proposal: Proposal | None
    safety: SafetyAssessment | None
    evidence: list[str]
    execution_id: uuid.UUID | None
    verification: Verification | None
    authorization: ExecutionAuthorization | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class AutonomyResponse(Contract):
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    mode: Mode
    status: Literal["monitoring", "ready", "blocked", "stopped", "executing", "uncertain"]
    ready: bool
    blocked_reasons: list[str]
    online_learning: Literal[False] = False
    production_dispatch: Literal[False] = False
    checkpoint_sha256: SHA256 | None
    approval_expires_at: AwareDatetime | None
    approved_by_user_id: str | None
    emergency_stopped: bool
    stopped_at: AwareDatetime | None
    stopped_by_user_id: str | None
    active_execution_id: uuid.UUID | None
    cancellation_status: Literal["none", "requested", "verified", "uncertain"]
    revision: int
    providers: ProviderStatuses
    last_observation: Observation | None
    last_decision: DecisionResponse | None
    decisions: list[DecisionResponse] = Field(max_length=100)
    history_limit: int
    updated_at: AwareDatetime | None
