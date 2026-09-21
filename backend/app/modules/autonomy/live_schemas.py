"""Private ADR023 operator contracts; no caller-supplied vectors or qualification flags."""

import uuid
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from app.modules.autonomy.artifact_io import ArtifactRef
from app.modules.autonomy.schemas import SHA256, Contract

OBSERVATION_CONTRACT = "nanfo.passive-measured-v4.v1"
ID = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")]
Nonnegative = Annotated[float, Field(strict=True, ge=0, le=1e9)]


class MeasuredFeatures(Contract):
    """Exact frozen numeric types, including integer-to-float canonical serialization."""

    path_capacity_mbps: list[Annotated[float, Field(strict=True, gt=0, le=100)]] = Field(min_length=2, max_length=2)
    path_utilization: list[Nonnegative] = Field(min_length=2, max_length=2)
    path_queue_packets: list[Nonnegative] = Field(min_length=2, max_length=2)
    latency_ms: Nonnegative | None
    loss_fraction: Annotated[float, Field(strict=True, ge=0, le=1)]
    goodput_mbps: Nonnegative
    offered_mbps: Annotated[float, Field(strict=True, gt=0, le=1e9)]
    actual_offered_mbps: Annotated[float, Field(strict=True, gt=0, le=1e9)]
    background_mbps: Nonnegative
    previous_action: Annotated[int, Field(strict=True, ge=0, le=1)]
    seconds_since_change: Nonnegative


class LiveScope(Contract):
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    snapshot_path: str = Field(min_length=1, max_length=256)


class BenchmarkSession(Contract):
    summary: ArtifactRef
    evidence: ArtifactRef
    attachment: ArtifactRef | None = None


class LiveInstallation(Contract):
    version: Literal[1]
    model_id: ID
    checkpoint: ArtifactRef
    qualification_protocol: Literal["adr014-test-only-v1", "adr024-rebuilt-evaluation-v1"] = "adr014-test-only-v1"
    parent_checkpoint: ArtifactRef | None = None
    lineage: ArtifactRef | None = None
    seed_audit: ArtifactRef | None = None
    source_directory: str = Field(min_length=1, max_length=256)
    source_sha256: dict[Annotated[str, Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*\.py$")], SHA256] = Field(
        min_length=1, max_length=64)
    contract_sha256: SHA256
    spec_sha256: SHA256
    runtime_versions: dict[str, str] = Field(min_length=1, max_length=10)
    observation_contract: Literal["nanfo.passive-measured-v4.v1"]
    runtime_action: Literal["linux-frr-host-route"]
    action_ids: list[ID] = Field(min_length=2, max_length=2)
    scopes: list[LiveScope] = Field(min_length=1, max_length=100)
    installed_at: AwareDatetime
    expires_at: AwareDatetime
    max_observation_age_seconds: int = Field(strict=True, ge=1, le=30)
    # Authentic pinned preregistration/selection and complete raw heldout evidence.
    plan: ArtifactRef
    selection: ArtifactRef
    report: ArtifactRef
    sessions: list[BenchmarkSession] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def unique_bindings(self):
        if (self.qualification_protocol == "adr024-rebuilt-evaluation-v1") != (self.parent_checkpoint is not None):
            raise ValueError("live_rebuilt_parent_required_only_for_rebuilt_protocol")
        rebuilt = self.qualification_protocol == "adr024-rebuilt-evaluation-v1"
        if (rebuilt and (self.lineage is None or self.seed_audit is None
                        or any(session.attachment is None for session in self.sessions))
                or not rebuilt and (self.lineage is not None or self.seed_audit is not None
                                    or any(session.attachment is not None for session in self.sessions))):
            raise ValueError("live_rebuilt_evidence_required_only_for_rebuilt_protocol")
        if (len(set(self.action_ids)) != 2 or self.expires_at <= self.installed_at
                or len({s.network_id for s in self.scopes}) != len(self.scopes)
                or len({s.snapshot_path for s in self.scopes}) != len(self.scopes)):
            raise ValueError("live_installation_bindings_invalid")
        return self


class PassiveSnapshot(Contract):
    version: Literal["nanfo.passive-measured-v4.v1"]
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    snapshot_id: uuid.UUID
    run_id: uuid.UUID
    observed_at: AwareDatetime
    window_started_at: AwareDatetime
    published_at: AwareDatetime
    source: Literal["operator-attested-measured-lab"]
    contract_sha256: SHA256
    spec_sha256: SHA256
    # Original frozen request/response evidence, not a pre-encoded vector.
    history: dict
    history_sha256: SHA256

    @model_validator(mode="after")
    def chronology(self):
        if not self.window_started_at < self.observed_at <= self.published_at:
            raise ValueError("passive_snapshot_chronology_invalid")
        if not 2 <= (self.observed_at - self.window_started_at).total_seconds() <= 30:
            raise ValueError("passive_snapshot_window_invalid")
        return self


class RuntimeResult(Contract):
    operation: Literal["qualify", "infer", "replay"]
    registry_sha256: SHA256
    checkpoint_sha256: SHA256
    weights_sha256: SHA256
    source_sha256: SHA256
    contract_sha256: SHA256
    spec_sha256: SHA256
    report_sha256: SHA256
    qualification_protocol: Literal["adr014-test-only-v1", "adr024-rebuilt-evaluation-v1"] = "adr014-test-only-v1"
    parent_checkpoint_sha256: SHA256 | None = None
    scope: Literal["stationary-campus-small-v4-scoped-benchmark"]
    execution: Literal["not_applied"] = "not_applied"
    safety_authorized: Literal[False] = False
    snapshot_sha256: SHA256 | None = None
    history_sha256: SHA256 | None = None
    input_sha256: SHA256 | None = None
    action: Literal[0, 1] | None = None
    action_path: list[str] | None = Field(default=None, min_length=3, max_length=3)
    probabilities: list[Annotated[float, Field(ge=0, le=1)]] | None = Field(default=None, min_length=2, max_length=2)
    value: float | None = None
    inference_seconds: float | None = Field(default=None, ge=0, le=30)

    @model_validator(mode="after")
    def complete_result(self):
        if self.operation != "qualify":
            if any(getattr(self, key) is None for key in (
                "history_sha256", "input_sha256", "action", "action_path", "probabilities", "value", "inference_seconds"
            )):
                raise ValueError("inference_result_incomplete")
            if abs(sum(self.probabilities) - 1) > 1e-6 or self.probabilities[self.action] != max(self.probabilities):
                raise ValueError("inference_result_policy_invalid")
            if self.operation == "infer" and self.snapshot_sha256 is None:
                raise ValueError("inference_snapshot_missing")
        return self
