"""NANFO Backend - Intent module Pydantic schemas.

Request/response schemas for intent validation baseline.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from app.core.canonical import canonical_json_bytes
from app.core.responses import APIResponse, ResponseMeta

# ADR-028: bounded, JSON-native intent documents are rejected with 422 at the API
# instead of failing later (JSONB/NaN/recursion) with a 500.
MAX_INTENT_PAYLOAD_BYTES = 64 * 1024
MAX_INTENT_PAYLOAD_DEPTH = 10
MAX_INTENT_OBJECT_KEYS = 128
MAX_INTENT_ARRAY_ITEMS = 1024
MAX_INTENT_KEY_LENGTH = 128
MAX_INTENT_NODES = 10_000

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def bounded_intent_document(value: Any) -> dict[str, Any]:
    """Validate an intent document: JSON-native values, bounded size, depth and fan-out.

    Depth counts nested containers (the top-level object is depth 1). Iterative, so
    adversarial nesting cannot exhaust the interpreter stack.
    """
    if not isinstance(value, dict):
        raise ValueError("intent must be a JSON object")
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > MAX_INTENT_NODES:
            raise ValueError("intent contains too many values")
        if isinstance(node, dict):
            if depth > MAX_INTENT_PAYLOAD_DEPTH:
                raise ValueError("intent nesting is too deep")
            if len(node) > MAX_INTENT_OBJECT_KEYS:
                raise ValueError("intent object has too many keys")
            for key, item in node.items():
                if not isinstance(key, str) or len(key) > MAX_INTENT_KEY_LENGTH:
                    raise ValueError("intent keys must be short strings")
                stack.append((item, depth + 1))
        elif isinstance(node, list):
            if depth > MAX_INTENT_PAYLOAD_DEPTH:
                raise ValueError("intent nesting is too deep")
            if len(node) > MAX_INTENT_ARRAY_ITEMS:
                raise ValueError("intent array is too long")
            stack.extend((item, depth + 1) for item in node)
        elif node is None or isinstance(node, (bool, str, int)):
            continue
        elif isinstance(node, float):
            if not math.isfinite(node):
                raise ValueError("intent numbers must be finite")
        else:
            raise ValueError("intent values must be JSON-native")
    try:
        size = len(canonical_json_bytes(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("intent must be JSON-serializable") from exc
    if size > MAX_INTENT_PAYLOAD_BYTES:
        raise ValueError("intent exceeds 64 KiB")
    return value


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


class ApprovalBinding(BaseModel):
    """The exact lab identity an operator approves (ADR-028 contract 3).

    ``plan_hash`` is the canonical SHA-256 of the normalized lab plan,
    ``binding_digest`` that of the trusted operator binding and ``run_id`` the
    observed lab run. Manual-approval lab execution must echo the server's
    current values or is rejected with 409 ``APPROVAL_BINDING_MISMATCH``.
    """

    model_config = ConfigDict(extra="forbid")

    plan_hash: Digest
    binding_digest: Digest
    run_id: uuid.UUID


class SimulationActionBinding(BaseModel):
    """Copy verbatim into ``scenario_config.action_binding`` (ADR-028 C18).

    ``network_state_sha256`` is the stable topology/configuration digest
    (``simulation.modeled.current_network_state_hash`` v2), not a sample hash.
    """

    intent_id: uuid.UUID
    plan_sha256: Digest
    network_state_sha256: Digest


class ValidateIntentRequest(BaseModel):
    workspace_id: uuid.UUID
    network_id: uuid.UUID | None = None
    intent: dict[str, Any] = Field(default_factory=dict, description=(
        f"UNIL intent document: JSON-native values only, at most {MAX_INTENT_PAYLOAD_BYTES} bytes serialized, "
        f"nesting depth {MAX_INTENT_PAYLOAD_DEPTH}, {MAX_INTENT_OBJECT_KEYS} keys per object and "
        f"{MAX_INTENT_ARRAY_ITEMS} items per array."))

    @field_validator("intent")
    @classmethod
    def bounded_intent(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_intent_document(value)


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
    # ADR-028 additive fields.
    idempotent_replay: bool = False
    approval_binding: ApprovalBinding | None = None
    simulation_action_binding: SimulationActionBinding | None = None


class ExecuteIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: uuid.UUID
    intent_id: uuid.UUID
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)
    manual_approval: StrictBool = False
    cancel: StrictBool = False
    simulation_id: uuid.UUID | None = None
    approval_binding: ApprovalBinding | None = None


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
    approval_binding: ApprovalBinding | None = None


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
    approval_binding: ApprovalBinding | None = None
    simulation_action_binding: SimulationActionBinding | None = None


class IntentResponseMeta(ResponseMeta):
    """Envelope meta plus ``idempotent_replay`` (true when a stored result is returned)."""

    idempotent_replay: bool = False


class ValidateIntentEnvelope(APIResponse[ValidateIntentResponse]):
    meta: IntentResponseMeta


class ExecuteIntentEnvelope(APIResponse[ExecuteIntentResponse]):
    meta: IntentResponseMeta
