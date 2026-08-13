"""Intent services.

Scope:
- Intent payload normalization and validation reason generation
- C5-safe workspace/network boundary checks
- Baseline explainability and confidence shaping for validated/rejected intents
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.publisher import publish_event
from app.modules.intent.repository import IntentRepository
from app.modules.network.repository import NetworkRepository
from app.modules.organization.service import WorkspaceService as OrgWorkspaceService

_SUPPORTED_ACTIONS = {
    "optimize_wireless_capacity",
    "reroute_path",
    "isolate_vlan",
    "throttle_qos",
}

_HIGH_IMPACT_ACTIONS = {
    "isolate_vlan",
    "reroute_path",
}


def _coerce_correlation_uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return uuid.uuid4()


def _coerce_non_empty_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _extract_unil_intent(intent_payload: Any) -> dict[str, Any]:
    if not isinstance(intent_payload, dict):
        return {}
    nested_intent = intent_payload.get("intent")
    if isinstance(nested_intent, dict):
        return nested_intent
    return intent_payload


def _build_reason(code: str, message: str, path: str | None = None) -> dict[str, str]:
    reason = {"code": code, "message": message}
    if path:
        reason["path"] = path
    return reason


def _confidence_band(score: float) -> str:
    if score >= 0.95:
        return "95-100"
    if score >= 0.80:
        return "80-94"
    if score >= 0.60:
        return "60-79"
    return "below_60"


class IntentValidationService:
    """Validate intent payloads and persist baseline lifecycle state."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = IntentRepository(db)
        self._network_repo = NetworkRepository(db)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def validate_intent(
        self,
        *,
        workspace_id: uuid.UUID,
        network_id: uuid.UUID | None,
        intent_payload: dict[str, Any],
        idempotency_key: str | None,
        correlation_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        await self._workspace_svc.get_active_workspace(workspace_id)

        now = datetime.now(UTC)
        normalized_intent = _extract_unil_intent(intent_payload)
        normalized_idempotency_key = _coerce_non_empty_text(idempotency_key) or None
        normalized_correlation_id = _coerce_correlation_uuid(correlation_id)
        reasons: list[dict[str, str]] = []

        action = _coerce_non_empty_text(normalized_intent.get("action"))
        if not action:
            reasons.append(
                _build_reason(
                    "ACTION_REQUIRED",
                    "Intent action is required.",
                    path="intent.action",
                )
            )
        elif action not in _SUPPORTED_ACTIONS:
            reasons.append(
                _build_reason(
                    "ACTION_UNSUPPORTED",
                    "Intent action is not supported by the baseline capability map.",
                    path="intent.action",
                )
            )

        scope = normalized_intent.get("scope")
        if not isinstance(scope, dict) or not scope:
            reasons.append(
                _build_reason(
                    "SCOPE_REQUIRED",
                    "Intent scope must be a non-empty object.",
                    path="intent.scope",
                )
            )

        constraints = normalized_intent.get("constraints")
        if constraints is not None and not isinstance(constraints, dict):
            reasons.append(
                _build_reason(
                    "CONSTRAINTS_INVALID",
                    "Intent constraints must be an object when provided.",
                    path="intent.constraints",
                )
            )

        if network_id is None:
            reasons.append(
                _build_reason(
                    "NETWORK_ID_REQUIRED",
                    "network_id is required for capability and dependency validation.",
                    path="network_id",
                )
            )
        else:
            network = await self._network_repo.get_by_id(network_id)
            if network is None:
                reasons.append(
                    _build_reason(
                        "NETWORK_NOT_FOUND",
                        "network_id does not reference an active network.",
                        path="network_id",
                    )
                )
            elif network.workspace_id != workspace_id:
                reasons.append(
                    _build_reason(
                        "NETWORK_WORKSPACE_MISMATCH",
                        "network_id is outside the requested workspace boundary.",
                        path="network_id",
                    )
                )

        required_checks = ["simulation_before_deployment"]
        if action in _HIGH_IMPACT_ACTIONS:
            required_checks.append("blast_radius_assessment")

        is_valid = len(reasons) == 0
        status_value = "validated" if is_valid else "rejected"
        capability_match = "matched" if is_valid else "failed"
        dependency_analysis = "complete" if is_valid else "failed"

        confidence_score = 0.84 if is_valid else 0.0
        confidence_band = _confidence_band(confidence_score)
        approval_required = True

        validation_result = {
            "is_valid": is_valid,
            "reasons": reasons,
            "required_checks": required_checks,
            "capability_match": capability_match,
            "dependency_analysis": dependency_analysis,
            "simulation_required": True,
            "policy_reference": "ADR-008",
            "validated_at": now.isoformat(),
        }
        explainability = {
            "summary": (
                "Intent passed baseline UNIL validation checks."
                if is_valid
                else "Intent rejected by baseline UNIL validation checks."
            ),
            "evidence": [reason["code"] for reason in reasons] if reasons else ["BASELINE_CHECKS_PASSED"],
            "alternatives_considered": ["manual_review"],
            "policy_reference": "ADR-008",
        }
        execution_provenance = {
            "pipeline_stage": "intent_validated",
            "status": status_value,
            "policy_reference": "ADR-008",
            "requested_by_user_id": requested_by_user_id,
            "validated_at": now.isoformat(),
        }

        intent = await self._repo.create(
            intent_id=uuid.uuid4(),
            workspace_id=workspace_id,
            network_id=network_id,
            intent_kind=(action or "unknown"),
            intent_payload=normalized_intent,
            status=status_value,
            validation_result=validation_result,
            execution_provenance=execution_provenance,
            explainability=explainability,
            confidence_score=confidence_score,
            confidence_band=confidence_band,
            approval_required=approval_required,
            idempotency_key=normalized_idempotency_key,
            correlation_id=normalized_correlation_id,
            queue_status="validated",
            stream_entry_id=None,
            warning=None,
            requested_by_user_id=requested_by_user_id,
            requested_at=now,
        )

        queue_status = "validated"
        stream_entry_id = None
        warning = None
        event_payload = {
            "intent_id": str(intent.intent_id),
            "workspace_id": str(intent.workspace_id),
            "network_id": str(intent.network_id) if intent.network_id is not None else None,
            "intent_kind": str(intent.intent_kind),
            "status": status_value,
            "validation_result": validation_result,
            "execution_provenance": execution_provenance,
            "explainability": explainability,
            "confidence": {
                "score": confidence_score,
                "band": confidence_band,
                "approval_required": approval_required,
            },
            "requested_by_user_id": requested_by_user_id,
        }

        try:
            stream_entry_id = await publish_event(
                redis=self._redis,
                event_type="intent.validated",
                source="intent",
                payload=event_payload,
                correlation_id=str(normalized_correlation_id),
            )
        except Exception:  # noqa: BLE001
            queue_status = "deferred"
            warning = "event_queue_unavailable"

        await self._repo.update_status(
            intent,
            status=status_value,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
        )
        await self._db.commit()

        return {
            "intent_id": str(intent.intent_id),
            "workspace_id": str(intent.workspace_id),
            "network_id": str(intent.network_id) if intent.network_id is not None else None,
            "status": str(intent.status),
            "intent_kind": str(intent.intent_kind),
            "validation": validation_result,
            "explainability": explainability,
            "confidence": {
                "score": confidence_score,
                "band": confidence_band,
                "approval_required": approval_required,
            },
            "idempotency_key": intent.idempotency_key,
            "correlation_id": str(intent.correlation_id),
            "requested_at": intent.requested_at.isoformat(),
            "queue_status": str(intent.queue_status),
            "stream_entry_id": intent.stream_entry_id,
            "warning": intent.warning,
        }


class IntentExecutionService:
    """Execute and read validated intents with baseline idempotent semantics."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = IntentRepository(db)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def execute_intent(
        self,
        *,
        workspace_id: uuid.UUID,
        intent_id: uuid.UUID,
        idempotency_key: str | None,
        correlation_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        await self._workspace_svc.get_active_workspace(workspace_id)

        normalized_idempotency_key = _coerce_non_empty_text(idempotency_key) or None
        normalized_correlation_id = _coerce_correlation_uuid(correlation_id)
        now = datetime.now(UTC)

        existing_by_key = None

        if normalized_idempotency_key:
            existing_by_key = await self._repo.get_by_idempotency_key(
                workspace_id=workspace_id,
                idempotency_key=normalized_idempotency_key,
            )
            if existing_by_key is not None:
                if existing_by_key.intent_id != intent_id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "INTENT_IDEMPOTENCY_CONFLICT",
                            "message": "idempotency_key is already bound to a different intent.",
                        },
                    )
                if existing_by_key.status in {
                    "execution_started",
                    "execution_completed",
                    "execution_failed",
                }:
                    return _serialize_intent(
                        existing_by_key,
                        idempotent_replay=True,
                        confidence_override={
                            "score": float(existing_by_key.confidence_score or 0.0),
                            "band": str(
                                existing_by_key.confidence_band
                                or _confidence_band(float(existing_by_key.confidence_score or 0.0))
                            ),
                            "approval_required": bool(existing_by_key.approval_required),
                        },
                    )

        intent = existing_by_key if existing_by_key is not None else await self._repo.get_by_id(intent_id)
        if intent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "INTENT_NOT_FOUND", "message": "Intent not found."},
            )
        if intent.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "INTENT_NOT_FOUND", "message": "Intent not found."},
            )

        if intent.status == "execution_started":
            if normalized_idempotency_key and intent.idempotency_key == normalized_idempotency_key:
                return _serialize_intent(
                    intent,
                    idempotent_replay=True,
                    confidence_override={
                        "score": float(intent.confidence_score or 0.0),
                        "band": str(
                            intent.confidence_band
                            or _confidence_band(float(intent.confidence_score or 0.0))
                        ),
                        "approval_required": bool(intent.approval_required),
                    },
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INTENT_ALREADY_EXECUTING",
                    "message": "Intent execution has already been started.",
                },
            )

        if intent.status != "validated":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INTENT_NOT_EXECUTABLE",
                    "message": "Intent must be in validated state before execution.",
                },
            )

        execution_provenance = dict(intent.execution_provenance) if isinstance(intent.execution_provenance, dict) else {}
        execution_provenance.update(
            {
                "pipeline_stage": "execution_started",
                "status": "execution_started",
                "executor": "intent_engine_baseline",
                "execution_mode": "deferred_hypervisor",
                "policy_reference": "ADR-008",
                "execution_started_at": now.isoformat(),
                "requested_by_user_id": requested_by_user_id,
                "correlation_id": str(normalized_correlation_id),
            }
        )

        explainability = dict(intent.explainability) if isinstance(intent.explainability, dict) else {}
        explainability.update(
            {
                "execution_posture": "simulation_required_before_hypervisor",
                "execution_summary": "Execution lifecycle started; hypervisor dispatch deferred to M9 scope.",
            }
        )

        confidence_score = float(intent.confidence_score or 0.0)
        confidence_band = str(intent.confidence_band or _confidence_band(confidence_score))
        approval_required = bool(intent.approval_required)

        update_kwargs: dict[str, Any] = {
            "status": "execution_started",
            "execution_provenance": execution_provenance,
            "explainability": explainability,
            "confidence_score": confidence_score,
            "confidence_band": confidence_band,
            "approval_required": approval_required,
            "queue_status": "queued",
            "warning": None,
        }
        if normalized_idempotency_key is not None:
            update_kwargs["idempotency_key"] = normalized_idempotency_key

        await self._repo.update_status(intent, **update_kwargs)

        stream_entry_id = None
        queue_status = "queued"
        warning = None
        event_payload = {
            "intent_id": str(intent.intent_id),
            "workspace_id": str(intent.workspace_id),
            "network_id": str(intent.network_id) if intent.network_id is not None else None,
            "intent_kind": str(intent.intent_kind),
            "status": "execution_started",
            "validation_result": (
                dict(intent.validation_result)
                if isinstance(intent.validation_result, dict)
                else {}
            ),
            "execution_provenance": execution_provenance,
            "explainability": explainability,
            "confidence": {
                "score": confidence_score,
                "band": confidence_band,
                "approval_required": approval_required,
            },
            "requested_by_user_id": requested_by_user_id,
        }

        try:
            stream_entry_id = await publish_event(
                redis=self._redis,
                event_type="intent.execution_started",
                source="intent",
                payload=event_payload,
                correlation_id=str(normalized_correlation_id),
            )
        except Exception:  # noqa: BLE001
            queue_status = "deferred"
            warning = "event_queue_unavailable"

        await self._repo.update_status(
            intent,
            status="execution_started",
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
        )
        await self._db.commit()

        return _serialize_intent(
            intent,
            idempotent_replay=False,
            confidence_override={
                "score": confidence_score,
                "band": confidence_band,
                "approval_required": approval_required,
            },
        )

    async def get_intent_detail(
        self,
        *,
        workspace_id: uuid.UUID,
        intent_id: uuid.UUID,
    ) -> dict[str, Any]:
        await self._workspace_svc.get_active_workspace(workspace_id)
        intent = await self._repo.get_by_id(intent_id)
        if intent is None or intent.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "INTENT_NOT_FOUND", "message": "Intent not found."},
            )
        return _serialize_intent(
            intent,
            idempotent_replay=False,
            confidence_override={
                "score": float(intent.confidence_score or 0.0),
                "band": str(
                    intent.confidence_band
                    or _confidence_band(float(intent.confidence_score or 0.0))
                ),
                "approval_required": bool(intent.approval_required),
            },
            detail_mode=True,
        )


def _serialize_intent(
    intent,
    *,
    idempotent_replay: bool,
    confidence_override: dict[str, Any],
    detail_mode: bool = False,
) -> dict[str, Any]:
    base = {
        "intent_id": str(intent.intent_id),
        "workspace_id": str(intent.workspace_id),
        "network_id": str(intent.network_id) if intent.network_id is not None else None,
        "status": str(intent.status),
        "intent_kind": str(intent.intent_kind),
        "validation_result": (
            dict(intent.validation_result)
            if isinstance(intent.validation_result, dict)
            else {}
        ),
        "execution_provenance": (
            dict(intent.execution_provenance)
            if isinstance(intent.execution_provenance, dict)
            else {}
        ),
        "explainability": (
            dict(intent.explainability)
            if isinstance(intent.explainability, dict)
            else {}
        ),
        "confidence": confidence_override,
        "idempotency_key": intent.idempotency_key,
        "queue_status": str(intent.queue_status),
        "stream_entry_id": intent.stream_entry_id,
        "warning": intent.warning,
        "correlation_id": str(intent.correlation_id),
        "requested_by_user_id": str(intent.requested_by_user_id),
        "requested_at": intent.requested_at.isoformat(),
        "updated_at": intent.updated_at.isoformat(),
    }
    if detail_mode:
        base["intent_payload"] = (
            dict(intent.intent_payload)
            if isinstance(intent.intent_payload, dict)
            else {}
        )
        base["created_at"] = intent.created_at.isoformat()
        return base

    base["idempotent_replay"] = idempotent_replay
    return base
