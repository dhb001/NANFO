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

from app.core.config import get_settings
from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.intent.hypervisor import HypervisorExecutionService
from app.modules.intent.repository import IntentRepository
from app.modules.network.service import NetworkService
from app.modules.organization.service import WorkspaceService as OrgWorkspaceService

logger = get_logger(__name__)

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


def _coerce_permissions_for_execute(raw_permissions: Any) -> set[str]:
    if not isinstance(raw_permissions, list):
        return set()
    normalized: set[str] = set()
    for raw in raw_permissions:
        permission = str(raw).strip().lower()
        if permission:
            normalized.add(permission)
    return normalized


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
        self._network_svc = NetworkService(db, redis)
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
        workspace = await self._workspace_svc.get_active_workspace(workspace_id, user_id=requested_by_user_id, require_write=True)

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
            try:
                network = await self._network_svc.assert_network_workspace_access(
                    network_id=network_id, requested_workspace_id=workspace_id,
                    actor_user_id=requested_by_user_id, require_write=True,
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                network = None
            if network is None:
                network_id = None
                reasons.append(
                    _build_reason(
                        "NETWORK_NOT_FOUND",
                        "network_id does not reference an active network.",
                        path="network_id",
                    )
                )
            elif network.workspace_id != workspace_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        required_checks = ["simulation_before_deployment"]
        if action in _HIGH_IMPACT_ACTIONS:
            required_checks.append("blast_radius_assessment")

        lab_validation = get_settings().EXECUTION_MODE == "emulation" and get_settings().EMULATION_CONTROL_ENABLED
        if lab_validation and not reasons:
            from app.modules.intent.lab import prepare_plan

            try:
                await prepare_plan(settings=get_settings(), db=self._db, redis=self._redis,
                    workspace_id=workspace_id, network_id=network_id, actor_id=requested_by_user_id,
                    payload=normalized_intent)
            except (ValueError, OSError, ImportError):
                reasons.append(_build_reason("LAB_PLAN_INVALID", "Lab plan, capabilities, binding or fresh observation invalid."))
            required_checks = ["explicit_manual_lab_approval", "current_authority_before_dispatch", "actual_lab_readback"]

        is_valid = len(reasons) == 0
        status_value = "validated" if is_valid else "rejected"
        capability_match = "baseline_schema_match" if is_valid else "failed"
        dependency_analysis = "not_performed"

        confidence_score = 0.0
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
            "validation_kind": "baseline_schema_only",
            "model_evidence": "unavailable",
        }
        explainability = {
            "summary": (
                "Intent passed baseline UNIL validation checks."
                if is_valid
                else "Intent rejected by baseline UNIL validation checks."
            ),
            "evidence": ([reason["code"] for reason in reasons] if reasons else ["BASELINE_SCHEMA_CHECKS_PASSED"])
            + ["MODEL_CONFIDENCE_UNAVAILABLE", "DEPENDENCY_EVALUATOR_UNAVAILABLE"],
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
        if lab_validation:
            validation_result.update(validation_kind="manual_lab_plan", policy_reference="ADR-010",
                                     capability_match="trusted_lab_plan" if is_valid else "failed")

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
            "org_id": str(workspace.org_id),
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

    async def _serialize_with_fresh_timestamps(
        self,
        intent,
        *,
        idempotent_replay: bool,
        confidence_override: dict[str, Any],
        detail_mode: bool = False,
    ) -> dict[str, Any]:
        # Ensure ORM-backed response attributes are loaded before sync serialization.
        # Refreshing all mapped columns prevents async lazy-load attempts (MissingGreenlet).
        await self._db.refresh(intent)
        return _serialize_intent(
            intent,
            idempotent_replay=idempotent_replay,
            confidence_override=confidence_override,
            detail_mode=detail_mode,
        )

    async def execute_intent(
        self,
        *,
        workspace_id: uuid.UUID,
        intent_id: uuid.UUID,
        idempotency_key: str | None,
        correlation_id: str,
        requested_by_user_id: str,
        requested_permissions: list[str],
        manual_approval: bool = False,
        cancel: bool = False,
    ) -> dict[str, Any]:
        settings = get_settings()
        if cancel or (settings.EXECUTION_MODE == "emulation" and settings.EMULATION_CONTROL_ENABLED):
            from app.modules.intent.execution import accept_execution

            intent, replay = await accept_execution(db=self._db, redis=self._redis, workspace_id=workspace_id,
                intent_id=intent_id, idempotency_key=_coerce_non_empty_text(idempotency_key) or None,
                correlation_id=_coerce_correlation_uuid(correlation_id), actor_id=requested_by_user_id,
                permissions=requested_permissions, manual_approval=manual_approval, cancel=cancel)
            return await self._serialize_with_fresh_timestamps(intent, idempotent_replay=replay,
                confidence_override={"score": 0.0, "band": "below_60", "approval_required": True})
        normalized_idempotency_key = _coerce_non_empty_text(idempotency_key) or None
        normalized_correlation_id = _coerce_correlation_uuid(correlation_id)
        now = datetime.now(UTC)

        if "execute:rollback" not in _coerce_permissions_for_execute(requested_permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INTENT_EXECUTION_PERMISSION_DENIED",
                    "message": "execute:rollback permission is required for intent execution.",
                },
            )

        workspace = await self._workspace_svc.get_active_workspace(workspace_id, user_id=requested_by_user_id, require_write=True)

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
                    return await self._serialize_with_fresh_timestamps(
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
                return await self._serialize_with_fresh_timestamps(
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

        execution_provenance_started = (
            dict(intent.execution_provenance) if isinstance(intent.execution_provenance, dict) else {}
        )
        execution_provenance_started.update(
            {
                "pipeline_stage": "execution_started",
                "status": "execution_started",
                "executor": "unavailable",
                "policy_reference": "ADR-008",
                "execution_started_at": now.isoformat(),
                "requested_by_user_id": requested_by_user_id,
                "correlation_id": str(normalized_correlation_id),
            }
        )

        explainability_started = (
            dict(intent.explainability) if isinstance(intent.explainability, dict) else {}
        )
        explainability_started.update(
            {
                "execution_posture": "simulation_required_before_hypervisor",
                "execution_summary": "Execution requested; no controller is installed and no dispatch occurred.",
            }
        )

        confidence_score = 0.0
        confidence_band = _confidence_band(confidence_score)
        approval_required = True

        update_kwargs: dict[str, Any] = {
            "status": "execution_started",
            "execution_provenance": execution_provenance_started,
            "explainability": explainability_started,
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
            "org_id": str(workspace.org_id),
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
            "execution_provenance": execution_provenance_started,
            "explainability": explainability_started,
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

        terminal_status = "execution_failed"
        terminal_event_type = f"intent.{terminal_status}"
        terminal_time = datetime.now(UTC)

        hypervisor_outcome = HypervisorExecutionService().execute(
            intent_id=intent.intent_id,
            intent_kind=str(intent.intent_kind),
            validation_result=(
                dict(intent.validation_result)
                if isinstance(intent.validation_result, dict)
                else {}
            ),
            correlation_id=normalized_correlation_id,
            requested_by_user_id=requested_by_user_id,
        )

        terminal_execution_provenance = dict(execution_provenance_started)
        terminal_execution_provenance.pop("rollback", None)
        terminal_execution_provenance.pop("execution_completed_at", None)
        terminal_execution_provenance.pop("completion_mode", None)
        terminal_explainability = dict(explainability_started)

        terminal_status = hypervisor_outcome.terminal_status
        terminal_event_type = f"intent.{terminal_status}"

        terminal_execution_provenance.update(
            {
                "pipeline_stage": "execution_failed",
                "status": "execution_failed",
                "execution_failed_at": terminal_time.isoformat(),
                "failure_reason": hypervisor_outcome.failure_reason,
                "verification": hypervisor_outcome.verification,
            }
        )
        terminal_explainability.update(
            {
                "execution_summary": hypervisor_outcome.execution_summary,
                "failure_reason": hypervisor_outcome.failure_reason,
            }
        )

        if queue_status == "deferred" and warning:
            terminal_execution_provenance["event_publication"] = {
                "status": "deferred",
                "warning": warning,
            }

        await self._repo.update_status(
            intent,
            status=terminal_status,
            execution_provenance=terminal_execution_provenance,
            explainability=terminal_explainability,
            queue_status=queue_status,
            warning=warning,
        )

        terminal_payload = {
            "org_id": str(workspace.org_id),
            "intent_id": str(intent.intent_id),
            "workspace_id": str(intent.workspace_id),
            "network_id": str(intent.network_id) if intent.network_id is not None else None,
            "intent_kind": str(intent.intent_kind),
            "status": terminal_status,
            "validation_result": (
                dict(intent.validation_result)
                if isinstance(intent.validation_result, dict)
                else {}
            ),
            "execution_provenance": terminal_execution_provenance,
            "explainability": terminal_explainability,
            "confidence": {
                "score": confidence_score,
                "band": confidence_band,
                "approval_required": approval_required,
            },
            "requested_by_user_id": requested_by_user_id,
        }

        try:
            terminal_stream_entry_id = await publish_event(
                redis=self._redis,
                event_type=terminal_event_type,
                source="intent",
                payload=terminal_payload,
                correlation_id=str(normalized_correlation_id),
            )
            stream_entry_id = terminal_stream_entry_id
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "intent_terminal_event_publish_failed",
                intent_id=str(intent.intent_id),
                event_type=terminal_event_type,
                status=terminal_status,
                correlation_id=str(normalized_correlation_id),
                error=str(exc),
            )

        await self._repo.update_status(
            intent,
            status=terminal_status,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
        )
        await self._db.commit()

        return await self._serialize_with_fresh_timestamps(
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
        user_id: str,
    ) -> dict[str, Any]:
        await self._workspace_svc.get_active_workspace(workspace_id, user_id=user_id)
        intent = await self._repo.get_by_id(intent_id)
        if intent is None or intent.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "INTENT_NOT_FOUND", "message": "Intent not found."},
            )
        return await self._serialize_with_fresh_timestamps(
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
        "confidence": {"score": 0.0, "band": "below_60", "approval_required": True},
        "idempotency_key": intent.idempotency_key,
        "queue_status": str(intent.queue_status),
        "stream_entry_id": intent.stream_entry_id,
        "warning": intent.warning,
        "correlation_id": str(intent.correlation_id),
        "requested_by_user_id": str(intent.requested_by_user_id),
        "requested_at": intent.requested_at.isoformat(),
        "updated_at": intent.updated_at.isoformat(),
    }
    if base["validation_result"].get("validation_kind") != "manual_lab_plan":
        base["validation_result"].update(
            validation_kind="baseline_schema_only", model_evidence="unavailable", dependency_analysis="not_performed",
        )
    if base["validation_result"].get("capability_match") == "matched":
        base["validation_result"]["capability_match"] = "baseline_schema_match"
    base["explainability"]["model_confidence"] = "unavailable; baseline schema checks are not model evidence"
    provenance = base["execution_provenance"]
    from app.modules.intent.lab import verified_completion

    measured_lab = (provenance.get("executor") == "manual_lab_v1" and provenance.get("phase") == "completed"
                    and verified_completion(provenance.get("verification", {}))
                    and bool(provenance.get("plan_hash")) and bool(provenance.get("execution_id")))
    if (base["status"] == "execution_completed" and not measured_lab) or provenance.get("executor") == "hypervisor_baseline":
        outcome = HypervisorExecutionService().execute(
            intent_id=intent.intent_id, intent_kind=str(intent.intent_kind), validation_result={},
            correlation_id=intent.correlation_id, requested_by_user_id=str(intent.requested_by_user_id),
        )
        base["status"] = outcome.terminal_status
        base["execution_provenance"] = {
            "status": outcome.terminal_status, "pipeline_stage": outcome.terminal_status,
            "executor": "unavailable", "failure_reason": outcome.failure_reason,
            "verification": outcome.verification, "legacy_baseline_unverified": True,
        }
        base["explainability"].update(execution_summary=outcome.execution_summary, failure_reason=outcome.failure_reason)
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
