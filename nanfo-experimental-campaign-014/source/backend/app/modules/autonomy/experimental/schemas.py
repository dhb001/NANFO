"""Versioned internal joined-loop contracts shared with transport and Simulation."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from app.modules.autonomy.live_schemas import MeasuredFeatures, PassiveSnapshot, RuntimeResult
from app.modules.autonomy.schemas import SHA256, Contract, Observation, Proposal, Qualification
from scripts.frozen_model_diagnostic import canonical_hash


def contract_digest(value):
    """Canonical SHA256 for both validated contracts and raw complete JSON records."""
    return canonical_hash(value.model_dump(mode="json") if hasattr(value, "model_dump") else value)

Name = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.:-]{1,200}$")]
Positive = Annotated[float, Field(gt=0, le=86400)]
PolicyKind = Literal["model", "fixed0", "fixed1", "heuristic"]


class Record(Contract):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, revalidate_instances="always")


class RuntimeIdentity(Record):
    resource_id: Name
    container_id: Name
    image_sha256: SHA256
    source_sha256: SHA256
    wrapper_sha256: SHA256
    disposable: Literal[True]
    network_disconnected: Literal[True]


class Route(Record):
    action_id: Name
    device_ids: tuple[Name, ...] = Field(min_length=1, max_length=64)
    path: tuple[Name, ...] = Field(min_length=2, max_length=64)


class VerificationThresholds(Record):
    min_goodput_mbps: float = Field(ge=0)
    max_loss_fraction: float = Field(ge=0, le=1)
    # UDP loss above and independently counted ICMP loss below are different streams.
    max_probe_loss_fraction: float = Field(default=0, ge=0, le=1)
    max_rtt_ms: float = Field(gt=0)
    min_probe_sent: int = Field(strict=True, ge=1)
    min_traffic_bytes: int = Field(strict=True, ge=1)


class ExperimentalPolicy(Record):
    version: Literal["nanfo.experimental-lab/v1"]
    run_id: UUID
    measurement_run_id: UUID | None = None
    policy_kind: PolicyKind = "model"
    wrapper_equivalence_sha256: SHA256 | None = None
    model_adapter_sha256: SHA256 | None = None
    actor_id: str = Field(min_length=1, max_length=200)
    network_id: UUID
    workspace_id: UUID
    runtime: RuntimeIdentity
    registry_sha256: SHA256
    checkpoint_sha256: SHA256
    weights_sha256: SHA256
    model_source_sha256: SHA256
    preregistration_sha256: SHA256
    evaluator_sha256: SHA256
    routes: tuple[Route, ...] = Field(min_length=1, max_length=32)
    assumptions: dict[str, Any] = Field(min_length=1)
    objectives: dict[str, Any] = Field(min_length=1)
    verification: VerificationThresholds
    max_observation_age_seconds: int = Field(strict=True, ge=1, le=30)
    min_dwell_seconds: float = Field(ge=0, le=3600)
    max_actions: int = Field(strict=True, ge=1, le=10000)
    action_window_seconds: Positive
    max_actions_per_window: int = Field(strict=True, ge=1, le=10000)
    max_action_duration_seconds: float = Field(gt=0, le=30)
    lease_seconds: int = Field(strict=True, ge=5, le=300)
    io_timeout_seconds: Positive
    poll_seconds: float = Field(gt=0, le=10)
    starts_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def bounded(self):
        if (self.expires_at <= self.starts_at or self.io_timeout_seconds >= self.lease_seconds
                or self.poll_seconds >= self.lease_seconds
                or len({r.action_id for r in self.routes}) != len(self.routes)):
            raise ValueError("experimental_policy_bounds_invalid")
        if (self.wrapper_equivalence_sha256 is None) != (self.model_adapter_sha256 is None):
            raise ValueError("experimental_wrapper_adapter_pins_required_together")
        return self


class MeasuredFrame(Record):
    snapshot: PassiveSnapshot
    features: MeasuredFeatures
    observation: Observation
    runtime: RuntimeIdentity
    provenance: dict[str, Any] = Field(min_length=1)
    telemetry_record_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def complete(self):
        s, o = self.snapshot, self.observation
        if (s.network_id != o.network_id or s.workspace_id != o.workspace_id
                or s.observed_at != o.observed_at or not o.fresh or not o.compatible
                or contract_digest(s.history) != s.history_sha256):
            raise ValueError("experimental_frame_binding_invalid")
        try:
            data = s.history["frames"][0]["response"]["data"]
            raw = data["observation"]
            if UUID(data["episode_id"]) != s.run_id:
                raise ValueError("experimental_raw_episode_mismatch")
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("experimental_complete_history_required") from exc
        if MeasuredFeatures.model_validate(raw) != self.features:
            raise ValueError("experimental_frame_features_mismatch")
        return self


class BaselineProposal(Record):
    action_id: Name
    checkpoint_sha256: None = None
    observation_contract: str
    evidence: list[str] = Field(min_length=1)


class ComparatorResult(Record):
    operation: Literal["compare"] = "compare"
    policy_kind: Literal["fixed0", "fixed1", "heuristic"]
    action: Literal[0, 1]
    action_path: list[str] = Field(min_length=2)
    input_sha256: SHA256
    rule: Literal["fixed-route/v1", "least-utilization-then-queue/v1"]
    probabilities: None = None
    value: None = None
    execution: Literal["not_applied"] = "not_applied"
    safety_authorized: Literal[False] = False


class InferenceRecord(Record):
    frame_sha256: SHA256
    policy_kind: PolicyKind = "model"
    result: RuntimeResult | ComparatorResult
    proposal: Proposal | BaselineProposal
    qualification: Qualification | None
    wrapper_equivalence_sha256: SHA256 | None = None
    model_adapter_sha256: SHA256 | None = None

    @model_validator(mode="after")
    def honest_policy(self):
        if self.policy_kind == "model":
            if not isinstance(self.result, RuntimeResult) or self.qualification is None or not isinstance(self.proposal, Proposal):
                raise ValueError("experimental_model_record_incomplete")
        elif (not isinstance(self.result, ComparatorResult) or self.result.policy_kind != self.policy_kind
              or self.qualification is not None or not isinstance(self.proposal, BaselineProposal)
              or self.wrapper_equivalence_sha256 is not None or self.model_adapter_sha256 is not None):
            raise ValueError("experimental_baseline_must_not_claim_model_qualification")
        return self


class BootstrapCommand(Record):
    request_id: UUID
    run_id: UUID
    runtime: RuntimeIdentity
    policy_sha256: SHA256
    receiver_policy_sha256: SHA256
    baseline: dict[str, Any] = Field(min_length=1)
    baseline_sha256: SHA256
    ownership_sha256: SHA256

    @model_validator(mode="after")
    def exact_baseline(self):
        if contract_digest(self.baseline) != self.baseline_sha256:
            raise ValueError("experimental_bootstrap_baseline_mismatch")
        return self


class BootstrapReceipt(Record):
    request_id: UUID
    command_sha256: SHA256
    measurement_run_id: UUID
    runtime: RuntimeIdentity
    registry_sha256: SHA256
    checkpoint_sha256: SHA256
    weights_sha256: SHA256
    model_source_sha256: SHA256
    baseline_sha256: SHA256
    ownership_sha256: SHA256
    evidence: dict[str, Any] = Field(min_length=1)


class BootstrapRecoveryReceipt(Record):
    request_id: UUID
    command_sha256: SHA256
    baseline_sha256: SHA256
    ownership_sha256: SHA256
    status: Literal["restored", "uncertain"]
    evidence: dict[str, Any] = Field(min_length=1)


class SimulationRecord(Record):
    frame_sha256: SHA256
    inference_sha256: SHA256
    policy_sha256: SHA256
    action_id: Name
    admitted: bool
    assumptions: dict[str, Any]
    objectives: dict[str, Any]
    reasons: tuple[str, ...]
    evaluator_sha256: SHA256
    result: dict[str, Any] = Field(min_length=1)


class ActionCommand(Record):
    request_id: UUID
    run_id: UUID
    resource_id: Name
    fence: int = Field(strict=True, gt=0)
    network_id: UUID
    workspace_id: UUID
    runtime: RuntimeIdentity
    route: Route
    policy_sha256: SHA256
    frame_sha256: SHA256
    inference_sha256: SHA256
    simulation_sha256: SHA256
    created_at: AwareDatetime
    expires_at: AwareDatetime


class PreparedAction(Record):
    command: ActionCommand
    baseline: dict[str, Any] = Field(min_length=1)
    baseline_sha256: SHA256
    ownership_sha256: SHA256

    @model_validator(mode="after")
    def exact_baseline(self):
        if contract_digest(self.baseline) != self.baseline_sha256:
            raise ValueError("experimental_baseline_digest_mismatch")
        return self


class ExecutionReceipt(Record):
    request_id: UUID
    action_sha256: SHA256
    action_id: Name
    status: Literal["applied", "uncertain"]
    evidence: dict[str, Any] = Field(min_length=1)


class VerificationRecord(Record):
    request_id: UUID
    action_sha256: SHA256
    run_id: UUID
    action_id: Name | None
    route_verified: bool
    observed_at: AwareDatetime
    window_started_at: AwareDatetime
    goodput_mbps: float | None = Field(ge=0)
    loss_fraction: float | None = Field(ge=0, le=1)
    rtt_ms: float | None = Field(ge=0)
    probe_sent: int | None = Field(strict=True, ge=0)
    probe_received: int | None = Field(strict=True, ge=0)
    traffic_bytes: int | None = Field(strict=True, ge=0)
    provenance: dict[str, Any] = Field(min_length=1)


class RecoveryReceipt(Record):
    request_id: UUID
    action_sha256: SHA256
    baseline_sha256: SHA256
    status: Literal["restored", "uncertain"]
    evidence: dict[str, Any] = Field(min_length=1)


def utcnow():
    return datetime.now(UTC)
