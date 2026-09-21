"""ADR018 public diagnostic contracts and private operator registry. No client paths."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.autonomy.artifact_io import SHA256, ArtifactRef

RegistryID = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")]


class DiagnosticSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class DiagnoseModelRequest(DiagnosticSchema):
    network_id: uuid.UUID
    history_reference: RegistryID


class BenchmarkMetadata(DiagnosticSchema):
    status: Literal["qualified_scoped_benchmark", "not_qualified"]
    scope: str = Field(min_length=1, max_length=2000)
    limitations: list[str] = Field(min_length=1, max_length=20)
    evidence: ArtifactRef


class RegisteredHistory(DiagnosticSchema):
    artifact: ArtifactRef
    network_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class RegisteredModel(DiagnosticSchema):
    model_id: RegistryID
    checkpoint_id: RegistryID
    network_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    checkpoint: ArtifactRef
    source_directory: str = Field(min_length=1, max_length=256)
    source_sha256: dict[str, SHA256] = Field(min_length=1, max_length=64)
    histories: dict[RegistryID, RegisteredHistory] = Field(max_length=100)
    benchmark: BenchmarkMetadata


class ModelDiagnosticRegistry(DiagnosticSchema):
    version: Literal[1]
    models: list[RegisteredModel] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_network_model(self):
        networks = [network for model in self.models for network in model.network_ids]
        if len(networks) != len(set(networks)):
            raise ValueError("one registered model per network required")
        if len({model.model_id for model in self.models}) != len(self.models):
            raise ValueError("duplicate model ID")
        for model in self.models:
            if any(not set(history.network_ids) <= set(model.network_ids)
                   for history in model.histories.values()):
                raise ValueError("history scope exceeds model scope")
        return self


class DiagnosticResult(DiagnosticSchema):
    model_id: RegistryID
    checkpoint_id: RegistryID
    history_reference: RegistryID
    registry_sha256: SHA256
    policy_sha256: SHA256
    checkpoint_weights_sha256: SHA256
    source_sha256: SHA256
    history_sha256: SHA256
    input_sha256: SHA256
    contract_hash: SHA256
    spec_hash: SHA256
    action: Literal[0, 1]
    action_path: list[str] = Field(min_length=1, max_length=10)
    probabilities: list[Annotated[float, Field(ge=0, le=1)]] = Field(min_length=2, max_length=2)
    value: float
    inference_seconds: float = Field(ge=0, le=30)
    artifact_validation_and_inference_seconds: float = Field(ge=0, le=30)
    subprocess_seconds: float = Field(ge=0, le=35)
    evidence: list[dict[str, float | int | list[float] | None]] = Field(min_length=1, max_length=3)
    history_kind: Literal["historical_measured_v4"] = "historical_measured_v4"
    live: Literal[False] = False
    execution: Literal["not_applied"] = "not_applied"
    safety_authorized: Literal[False] = False
    probabilities_are_safety_confidence: Literal[False] = False
    benchmark_status: Literal["qualified_scoped_benchmark", "not_qualified"]
    benchmark_scope: str
    benchmark_limitations: list[str]
    benchmark_evidence_sha256: SHA256

    @model_validator(mode="after")
    def normalized_policy(self):
        if abs(sum(self.probabilities) - 1) > 1e-6:
            raise ValueError("invalid probabilities")
        if self.probabilities[self.action] != max(self.probabilities):
            raise ValueError("non-deterministic action")
        return self


class ModelDiagnosticRecord(DiagnosticSchema):
    diagnostic_id: uuid.UUID
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    actor_id: str
    created_at: datetime
    result: DiagnosticResult


class RegisteredModelStatus(DiagnosticSchema):
    model_id: RegistryID
    checkpoint_id: RegistryID
    checkpoint_sha256: SHA256
    history_references: list[RegistryID]
    status: Literal["operator_registered"] = "operator_registered"
    benchmark_status: Literal["qualified_scoped_benchmark", "not_qualified"]
    benchmark_scope: str
    benchmark_limitations: list[str]


class ModelDiagnosticsResponse(DiagnosticSchema):
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    status: Literal["operator_registered", "unavailable"]
    reasons: list[str]
    model: RegisteredModelStatus | None
    diagnostics: list[ModelDiagnosticRecord]
    live_history_status: Literal["unavailable"] = "unavailable"
    safety_authorized: Literal[False] = False
    production_dispatch: Literal[False] = False
