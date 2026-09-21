"""NANFO Backend - Intent module Pydantic schemas.

Request/response schemas for intent validation baseline.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ValidationReason(BaseModel):
    code: str
    message: str
    path: str | None = None


class IntentValidationState(BaseModel):
    is_valid: bool
    reasons: list[ValidationReason] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
    capability_match: str
    dependency_analysis: str
    simulation_required: bool
    policy_reference: str
    validated_at: datetime
    validation_kind: str = "baseline_schema_only"
    model_evidence: str = "unavailable"


class IntentExplainability(BaseModel):
    summary: str
    evidence: list[str] = Field(default_factory=list)
    alternatives_considered: list[str] = Field(default_factory=list)
    policy_reference: str


class IntentConfidenceState(BaseModel):
    score: float
    band: str
    approval_required: bool


class ValidateIntentRequest(BaseModel):
    workspace_id: uuid.UUID
    network_id: uuid.UUID | None = None
    intent: dict[str, Any] = Field(default_factory=dict)


class ValidateIntentResponse(BaseModel):
    intent_id: uuid.UUID
    workspace_id: uuid.UUID
    network_id: uuid.UUID | None
    status: str
    intent_kind: str
    validation: IntentValidationState
    explainability: IntentExplainability
    confidence: IntentConfidenceState
    idempotency_key: str | None
    correlation_id: uuid.UUID
    requested_at: datetime
    queue_status: str = "validated"
    stream_entry_id: str | None = None
    warning: str | None = None


class ExecuteIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: uuid.UUID
    intent_id: uuid.UUID
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)
    manual_approval: StrictBool = False
    cancel: StrictBool = False
    simulation_id: uuid.UUID | None = None


class ExecuteIntentResponse(BaseModel):
    intent_id: uuid.UUID
    workspace_id: uuid.UUID
    network_id: uuid.UUID | None
    status: str
    intent_kind: str
    queue_status: str
    stream_entry_id: str | None
    warning: str | None
    validation_result: dict[str, Any]
    execution_provenance: dict[str, Any]
    explainability: dict[str, Any]
    confidence: IntentConfidenceState
    idempotency_key: str | None
    correlation_id: uuid.UUID
    requested_by_user_id: str
    requested_at: datetime
    updated_at: datetime
    idempotent_replay: bool


class IntentDetailResponse(BaseModel):
    intent_id: uuid.UUID
    workspace_id: uuid.UUID
    network_id: uuid.UUID | None
    status: str
    intent_kind: str
    intent_payload: dict[str, Any]
    validation_result: dict[str, Any]
    execution_provenance: dict[str, Any]
    explainability: dict[str, Any]
    confidence: IntentConfidenceState
    idempotency_key: str | None
    queue_status: str
    stream_entry_id: str | None
    warning: str | None
    correlation_id: uuid.UUID
    requested_by_user_id: str
    requested_at: datetime
    created_at: datetime
    updated_at: datetime
