"""Transactional ADR-010 acceptance and lifecycle projection."""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.modules.intent.lab import Mailbox, PendingLabCommand, digest, prepare_plan
from app.modules.intent.models import IntentExecution, IntentOutbox
from app.modules.intent.repository import ExecutionRepository, IntentRepository
from app.modules.organization.service import WorkspaceService


def project_execution(intent, job, *, event: bool = False, db=None):
    result = job.result or {}
    status = "execution_started" if job.blocks_lab else (
        "execution_completed" if job.phase == "completed" else "execution_failed"
    )
    # Uncertainty is not success or verified failure. It continues to exclude successors.
    intent.status = status
    intent.queue_status = "outbox_pending"
    intent.confidence_score = 0.0
    intent.confidence_band = "below_60"
    intent.approval_required = True
    intent.execution_provenance = {
        "executor": "manual_lab_v1", "policy_reference": "ADR-010", "execution_id": str(job.execution_id),
        "status": status, "phase": job.phase, "pipeline_stage": status,
        "manual_approval": True, "approved_by_user_id": job.actor_id, "approved_at": job.approved_at.isoformat(),
        "plan_hash": job.command["plan_hash"], "binding_digest": job.command["binding_digest"],
        "run_id": job.command["run_id"], "deadline": job.command["deadline"],
        "dispatch_expires_at": job.command.get("dispatch_expires_at"),
        "verification": result.get("verification", {"status": "not_performed"}),
        "rollback": result.get("rollback"), "failure_reason": job.failure_reason,
        "uncertain": job.phase == "uncertain", "blocks_lab": job.blocks_lab,
        "cancel_requested": job.cancel_requested,
        "cancelled_by_user_id": job.cancelled_by_user_id,
        "cancellation_requested_at": job.cancellation_requested_at.isoformat() if job.cancellation_requested_at else None,
        "completion_scope": "configuration_readback_and_reachability",
        "traffic_verification": {"status": "not_performed"},
        "completed_at": result.get("completed_at"),
        "execution_started_at": job.approved_at.isoformat(),
    }
    if not job.blocks_lab:
        intent.execution_provenance[f"{status}_at"] = result.get("completed_at") or datetime.now(UTC).isoformat()
    intent.explainability = {**intent.explainability, "policy_reference": "ADR-010",
                            "execution_summary": "Manual lab configuration readback and reachability; operation-specific traffic effects are not implied.",
                            "model_confidence": "unavailable"}
    if event:
        event_id = uuid.uuid4()
        payload = {
            "org_id": str(job.org_id),
            "intent_id": str(intent.intent_id), "workspace_id": str(intent.workspace_id),
            "network_id": str(intent.network_id), "intent_kind": intent.intent_kind, "status": status,
            "validation_result": intent.validation_result, "execution_provenance": intent.execution_provenance,
            "explainability": intent.explainability,
            "confidence": {"score": 0.0, "band": "below_60", "approval_required": True},
            "requested_by_user_id": job.actor_id,
            "actor_id": job.cancelled_by_user_id or job.actor_id,
        }
        job.outbox_sequence += 1
        db.add(IntentOutbox(event_id=event_id, execution_id=job.execution_id, sequence=job.outbox_sequence, envelope=copy.deepcopy({
            "event_id": str(event_id), "event_type": f"intent.{status}", "source": "intent", "version": "1",
            "timestamp": datetime.now(UTC).isoformat(), "correlation_id": str(intent.correlation_id),
            "payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
        })))


async def accept_execution(*, db, redis, workspace_id, intent_id, idempotency_key, correlation_id,
                           actor_id, permissions, manual_approval, cancel):
    if not {"write:config", "execute:rollback"}.issubset(permissions):
        raise HTTPException(403, detail={"code": "INTENT_EXECUTION_PERMISSION_DENIED", "message": "Execution permissions required."})
    workspace = await WorkspaceService(db=db, redis=redis).get_active_workspace(workspace_id, user_id=actor_id, require_write=True)
    repo = ExecutionRepository(db)
    key = idempotency_key or f"intent:{intent_id}"
    if len(key) > 120:
        raise HTTPException(400, detail="Idempotency key exceeds 120 characters.")
    intent = (await IntentRepository(db).get_by_id(intent_id) if cancel
              else await IntentRepository(db).lock_intent(intent_id, workspace_id))
    if intent is None or intent.workspace_id != workspace_id:
        raise HTTPException(404, detail={"code": "INTENT_NOT_FOUND", "message": "Intent not found."})
    request_hash = digest({"intent_id": str(intent_id), "workspace_id": str(workspace_id),
                           "actor_id": actor_id, "manual_approval": manual_approval,
                           "intent": intent.intent_payload})
    existing = await repo.existing(workspace_id, intent_id, key)
    if cancel:
        job = next((job for job in existing if job.intent_id == intent_id), None)
        if job is None:
            raise HTTPException(409, detail="No durable execution to cancel.")
        try:
            changed = await repo.request_cancel(job.execution_id, actor_id)
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(409, detail="Another execution owns the lab; cannot cancel this policy.") from exc
        await db.refresh(job)
        if not changed:
            await db.commit()
            await db.refresh(intent)
            return intent, True
        if job.blocks_lab:
            job.phase = "cancelling"
        project_execution(intent, job, event=changed, db=db)
        await db.commit()
        return intent, True
    if existing:
        if len(existing) != 1 or existing[0].request_key != key or existing[0].request_hash != request_hash:
            raise HTTPException(409, detail={"code": "INTENT_IDEMPOTENCY_CONFLICT", "message": "Execution request identity already used."})
        await db.commit()
        return intent, True
    if intent.status != "validated":
        raise HTTPException(409, detail={"code": "INTENT_NOT_EXECUTABLE", "message": "Validated intent required."})
    if manual_approval is not True:
        raise HTTPException(409, detail={"code": "MANUAL_APPROVAL_REQUIRED", "message": "Explicit manual lab approval required."})
    settings = get_settings()
    try:
        Mailbox(settings)
        plan, binding, snapshot = await prepare_plan(settings=settings, db=db, redis=redis,
            workspace_id=workspace_id, network_id=intent.network_id, actor_id=actor_id, payload=intent.intent_payload)
    except (ValueError, OSError, ImportError) as exc:
        raise HTTPException(409, detail={"code": "LAB_PRECONDITION_FAILED", "message": "Lab plan, binding, authority or observation unavailable."}) from exc
    now = datetime.now(UTC)
    command = PendingLabCommand(version=1, execution_id=uuid.uuid4(), run_id=snapshot.run_id,
        binding_digest=digest(binding.model_dump(mode="json")), plan_hash=digest(plan.model_dump(mode="json")),
        fence=1, deadline=now + timedelta(seconds=settings.EMULATION_EXECUTION_TIMEOUT_SECONDS), operation="execute", plan=plan)
    job = IntentExecution(execution_id=command.execution_id, intent_id=intent_id, workspace_id=workspace_id,
        org_id=workspace.org_id, outbox_sequence=0,
        request_key=key, request_hash=request_hash, lab_key=binding.topology_id,
        actor_id=actor_id, approved_at=now, command=command.model_dump(mode="json"),
        phase="accepted", blocks_lab=True, cancel_requested=False, fence=0)
    intent.correlation_id = correlation_id
    intent.idempotency_key = key
    db.add(job)
    try:
        await db.flush()
        project_execution(intent, job, event=True, db=db)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, detail={"code": "LAB_EXECUTION_CONFLICT", "message": "Request already used or lab has an unresolved execution."}) from exc
    return intent, False
