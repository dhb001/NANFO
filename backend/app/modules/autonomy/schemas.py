"""Concrete ADR-012 REST and provider contracts; no experiment vector fabrication."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from app.core.canonical import canonical_json_bytes, canonical_sha256
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
    # C17: autonomous dispatch needs calibrated confidence >= min_confidence. The floor is
    # the constitution's automatic-execution tier (aios.md §5); operators may only tighten it.
    min_confidence: float = Field(default=0.95, strict=True, ge=0.95, le=1.0)
    # Honoured only in the explicitly enabled experimental lab (NANFO_EXPERIMENTAL_LAB_ENABLED
    # with EXECUTION_MODE=emulation); ignored everywhere else, never a production bypass.
    allow_uncalibrated_confidence: bool = Field(default=False, strict=True)


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
    # C17: whether operational.allow_uncalibrated_confidence can take effect in this deployment.
    allow_uncalibrated_confidence_honoured: bool = False
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


#: Raw frozen-policy action probability (softmax output). It is a model output, never a
#: calibrated confidence: C17 forbids labelling it calibrated.
POLICY_PROBABILITY_METHOD = "policy_action_probability"
UNCALIBRATED_ONLY_METHODS = frozenset({POLICY_PROBABILITY_METHOD})


class Confidence(Contract):
    """Typed confidence carried by every AI proposal (constitution §2, ADR-028 C17)."""

    value: float = Field(strict=True, ge=0, le=1)
    method: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.:/-]{0,127}$")
    calibrated: bool = Field(strict=True)
    calibration_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def honest_calibration(self):
        if self.calibrated and self.method in UNCALIBRATED_ONLY_METHODS:
            raise ValueError("raw_policy_probability_cannot_be_calibrated")
        if self.calibrated != (self.calibration_id is not None):
            raise ValueError("calibration_id_required_exactly_for_calibrated_confidence")
        return self


class Proposal(Contract):
    action_id: str = Field(min_length=1, max_length=128)
    checkpoint_sha256: SHA256
    observation_contract: str
    evidence: list[str] = Field(min_length=1, max_length=100)
    # Mandatory for every new proposal (the worker never persists one without it); absent
    # only in pre-C17 history, whose canonical digests must stay byte-identical.
    confidence: Confidence | None = None

    @model_serializer(mode="wrap")
    def preserve_historical_identity(self, handler):
        data = handler(self)
        if self.confidence is None:
            data.pop("confidence", None)
        return data


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
    """Strict canonical JSON text of a contract (ADR-028 C20; byte-identical to the historical encoding)."""
    return canonical_json_bytes(value.model_dump(mode="json")).decode("ascii")


def contract_digest(value) -> str:
    return canonical_sha256(value.model_dump(mode="json"))


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


#: Internal reasons token recording how many identical coalescible cycles one decision row
#: stands for (ADR-028 fix 6; the row's updated_at is the last time such a cycle was seen).
#: It lives in `reasons` (not a telemetry-evidence field, so folding never re-pins evidence)
#: and is stripped from every API projection in favour of `repeat_count`.
COALESCED_CYCLES_PREFIX = "coalesced_cycles:"


def coalesced_cycles(reasons) -> int:
    for item in reasons or ():
        if isinstance(item, str) and item.startswith(COALESCED_CYCLES_PREFIX):
            try:
                return max(1, int(item.removeprefix(COALESCED_CYCLES_PREFIX)))
            except ValueError:
                return 1
    return 1


class _DecisionDerived(Contract):
    """Additive derived fields shared by full and summary decision projections."""

    #: C17 confidence of the persisted proposal (None for decisions without a proposal).
    confidence: Confidence | None = None
    #: Identical no-change cycles this row stands for (>= 1); see last_seen_at.
    repeat_count: int = Field(default=1, ge=1)
    last_seen_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def derive(self):
        proposal = getattr(self, "proposal", None)
        if self.confidence is None and proposal is not None:
            self.confidence = proposal.confidence
        reasons = getattr(self, "reasons", None) or []
        if any(isinstance(item, str) and item.startswith(COALESCED_CYCLES_PREFIX) for item in reasons):
            self.repeat_count = coalesced_cycles(reasons)
            self.reasons = [item for item in reasons if not str(item).startswith(COALESCED_CYCLES_PREFIX)]
        self.last_seen_at = getattr(self, "updated_at", None)
        return self


class DecisionResponse(_DecisionDerived):
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
    projection: Literal["full"] = "full"


class ObservationSummary(Contract):
    """Observation without its sample payload (history lists never carry blobs)."""

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
    evidence: list[str] = Field(default_factory=list, max_length=100)
    #: Always empty in summaries (kept for client type compatibility); see sample_count.
    samples: list[ObservationSample] = Field(default_factory=list, max_length=0)
    sample_count: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def drop_samples(cls, data):
        if isinstance(data, dict) and "samples" in data:
            data = dict(data)
            samples = data.pop("samples") or []
            data.setdefault("sample_count", len(samples))
        return data


_BINDING_SUMMARY_KEYS = ("workspace_id", "observation_sha256", "proposal_sha256", "calibration_sha256",
                         "selected_action_sha256", "evaluated_at_unix_seconds")


class SafetyBindingSummary(Contract):
    """Binding digests only; the bound provider inputs stay in the full decision."""

    workspace_id: uuid.UUID
    observation_sha256: SHA256
    proposal_sha256: SHA256
    calibration_sha256: SHA256
    selected_action_sha256: SHA256
    evaluated_at_unix_seconds: float

    @model_validator(mode="before")
    @classmethod
    def digests_only(cls, data):
        if isinstance(data, dict):
            return {key: data[key] for key in _BINDING_SUMMARY_KEYS if key in data}
        return data


class SafetySummary(Contract):
    admissible: bool
    action_id: str | None = None
    model_version: str
    reasons: list[str] = Field(default_factory=list, max_length=32)
    evidence: list[str] = Field(default_factory=list, max_length=100)
    certificate: SafetyCertificate | None = None
    binding: SafetyBindingSummary | None = None

    @model_validator(mode="before")
    @classmethod
    def drop_inputs(cls, data):
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if key != "selected_action"}
        return data


class DecisionSummary(_DecisionDerived):
    """Bounded list projection of a decision (ADR-028 fix 6); `last_decision` stays full."""

    decision_id: uuid.UUID
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    actor_id: str
    mode: Mode
    control_revision: int
    status: DecisionStatus
    reasons: list[str]
    checkpoint_sha256: SHA256 | None
    observation: ObservationSummary | None
    proposal: Proposal | None
    safety: SafetySummary | None
    evidence: list[str]
    execution_id: uuid.UUID | None
    verification: Verification | None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    projection: Literal["summary"] = "summary"


class PendingApproval(Contract):
    """C25 two-person switch: request awaiting a different approver's identical PUT."""

    requested_by_user_id: str
    mode: Mode
    expected_revision: int
    checkpoint_sha256: SHA256 | None
    approval_expires_at: AwareDatetime | None
    requested_at: AwareDatetime
    expires_at: AwareDatetime


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
    decisions: list[DecisionSummary] = Field(max_length=100)
    history_limit: int
    updated_at: AwareDatetime | None
    pending_approval: PendingApproval | None = None
