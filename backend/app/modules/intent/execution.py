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

MAX_REQUEST_KEY_LENGTH = 120


def _text(value) -> str | None:
    return (str(value).strip() if value is not None else "") or None


async def resolve_execution_key(repo: IntentRepository, *, workspace_id, intent, supplied) -> str | None:
    """ADR-028 C3: execution identity is the intent's stored ``idempotency_key``.

    A supplied key must equal it (clients reuse the stored key); a key bound to a
    different intent in the workspace, or a different key for an intent that already
    has one, is 409 ``INTENT_IDEMPOTENCY_CONFLICT``. Without a stored key the
    supplied key becomes the intent's identity.
    """
    stored, supplied = _text(intent.idempotency_key), _text(supplied)
    if supplied is not None and len(supplied) > MAX_REQUEST_KEY_LENGTH:
        # Client keys are bounded; stored keys (including migration 0030's
        # "<key>~dup~<intent_id>" renames) are server identities and are not.
        raise HTTPException(400, detail={"code": "IDEMPOTENCY_KEY_INVALID",
                                         "message": "Idempotency key exceeds 120 characters."})
    if supplied is None or supplied == stored:
        return stored
    owner = await repo.get_by_idempotency_key(workspace_id=workspace_id, idempotency_key=supplied)
    if owner is not None and owner.intent_id != intent.intent_id:
        raise HTTPException(409, detail={"code": "INTENT_IDEMPOTENCY_CONFLICT",
                                         "message": "idempotency_key is already bound to a different intent."})
    if stored is not None:
        raise HTTPException(409, detail={"code": "INTENT_IDEMPOTENCY_CONFLICT",
                                         "message": "Execute and cancel must reuse the intent's stored idempotency_key."})
    return supplied


def outbox_event_id(execution_id: uuid.UUID, sequence: int) -> uuid.UUID:
    """Deterministic per execution transition (ADR-028): never a fresh random identity."""
    return uuid.uuid5(execution_id, f"intent-outbox:{sequence}")


def _enqueue(db, job, *, event_id: uuid.UUID, event_type: str, correlation_id, payload: dict) -> None:
    job.outbox_sequence += 1
    db.add(IntentOutbox(event_id=event_id, execution_id=job.execution_id, sequence=job.outbox_sequence, envelope=copy.deepcopy({
        "event_id": str(event_id), "event_type": event_type, "source": "intent", "version": "1",
        "timestamp": datetime.now(UTC).isoformat(), "correlation_id": str(correlation_id),
        "payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
    })))


def approval_binding_matches(supplied, *, plan_hash, binding_digest, run_id) -> bool:
    if not isinstance(supplied, dict):
        return False
    try:
        return (supplied.get("plan_hash") == plan_hash and supplied.get("binding_digest") == binding_digest
                and str(uuid.UUID(str(supplied.get("run_id")))) == str(uuid.UUID(str(run_id))))
    except (TypeError, ValueError, AttributeError):
        return False


def _approval_mismatch() -> HTTPException:
    return HTTPException(409, detail={"code": "APPROVAL_BINDING_MISMATCH",
        "message": "approval_binding must equal the current plan_hash, binding_digest and run_id; "
                   "refresh the intent detail and approve the current lab identity."})


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
    command = job.command if isinstance(job.command, dict) else {}
    approved_plan = command.get("plan")
    try:
        if not isinstance(approved_plan, dict) or digest(approved_plan) != command.get("plan_hash"):
            approved_plan = None
    except (ValueError, TypeError):
        approved_plan = None
    evidence = job.simulation_evidence if isinstance(job.simulation_evidence, dict) else None
    intent.execution_provenance = {
        "executor": "manual_lab_v1", "policy_reference": "ADR-010", "execution_id": str(job.execution_id),
        "status": status, "phase": job.phase, "pipeline_stage": status,
        "manual_approval": True, "approved_by_user_id": job.actor_id, "approved_at": job.approved_at.isoformat(),
        "plan_hash": command.get("plan_hash"), "binding_digest": command.get("binding_digest"),
        "approved_plan": copy.deepcopy(approved_plan),
        "run_id": command.get("run_id"), "deadline": command.get("deadline"),
        "dispatch_expires_at": command.get("dispatch_expires_at"),
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
        # ADR-028 C18: the simulation evidence bound into this execution record.
        "simulation_id": evidence.get("simulation_id") if evidence else None,
        "simulation_evidence": copy.deepcopy(evidence),
    }
    if not job.blocks_lab:
        intent.execution_provenance[f"{status}_at"] = result.get("completed_at") or datetime.now(UTC).isoformat()
    intent.explainability = {**intent.explainability, "policy_reference": "ADR-010",
                            "execution_summary": "Manual lab configuration readback and reachability; operation-specific traffic effects are not implied.",
                            "model_confidence": "unavailable"}
    if event:
        sequence = job.outbox_sequence + 1
        payload = {
            "org_id": str(job.org_id),
            "intent_id": str(intent.intent_id), "workspace_id": str(intent.workspace_id),
            "network_id": str(intent.network_id), "intent_kind": intent.intent_kind, "status": status,
            "validation_result": intent.validation_result, "execution_provenance": intent.execution_provenance,
            "explainability": intent.explainability,
            "confidence": {"score": 0.0, "band": "below_60", "approval_required": True},
            "requested_by_user_id": job.actor_id,
            "actor_id": job.cancelled_by_user_id or job.actor_id,
            # ADR-028: lifecycle names stay the four documented ones; these additive
            # fields distinguish accepted/cancelling/uncertain/... transitions that
            # share ``intent.execution_started``.
            "phase": job.phase,
            "sequence": sequence,
        }
        _enqueue(db, job, event_id=outbox_event_id(job.execution_id, sequence), event_type=f"intent.{status}",
                 correlation_id=intent.correlation_id, payload=payload)


def _enqueue_pending_validated_event(db, intent, job, org_id) -> None:
    """A validate event still deferred when execution is accepted rides the outbox first."""
    if intent.queue_status != "deferred":
        return
    from app.modules.intent.service import validated_event

    event_type, event_id, payload, correlation = validated_event(intent, org_id)
    _enqueue(db, job, event_id=uuid.UUID(event_id), event_type=event_type, correlation_id=correlation, payload=payload)


async def accept_execution(*, db, redis, workspace_id, intent_id, idempotency_key, correlation_id,
                           actor_id, permissions, manual_approval, cancel, simulation_id=None,
                           approval_binding=None):
    from app.modules.intent.service import is_high_impact, require_distinct_approver

    if not {"write:config", "execute:rollback"}.issubset(permissions):
        raise HTTPException(403, detail={"code": "INTENT_EXECUTION_PERMISSION_DENIED", "message": "Execution permissions required."})
    workspace = await WorkspaceService(db=db, redis=redis).get_active_workspace(workspace_id, user_id=actor_id, require_write=True)
    repo = ExecutionRepository(db)
    intents = IntentRepository(db)
    intent = (await intents.get_by_id(intent_id) if cancel
              else await intents.lock_intent(intent_id, workspace_id))
    if intent is None or intent.workspace_id != workspace_id:
        raise HTTPException(404, detail={"code": "INTENT_NOT_FOUND", "message": "Intent not found."})
    stored_key = _text(getattr(intent, "idempotency_key", None))
    if cancel:
        # Safety action: the durable execution is the identity; a stale client key
        # must never block cancellation.
        key = stored_key or _text(idempotency_key) or f"intent:{intent_id}"
    else:
        key = await resolve_execution_key(intents, workspace_id=workspace_id, intent=intent,
                                          supplied=idempotency_key) or f"intent:{intent_id}"
    prepared, simulation_evidence = None, None
    if simulation_id is not None and not cancel:
        from app.modules.simulation.modeled import current_network_state_hash
        from app.modules.simulation.service import SimulationStartService

        try:
            prepared = await prepare_plan(settings=get_settings(), db=db, redis=redis,
                workspace_id=workspace_id, network_id=intent.network_id, actor_id=actor_id, payload=intent.intent_payload)
        except (ValueError, OSError, ImportError) as exc:
            raise HTTPException(409, detail={"code": "SIMULATION_EVIDENCE_REJECTED",
                "message": "Current actual network state and normalized plan unavailable."}) from exc
        plan, binding, snapshot = prepared
        simulation_evidence = await SimulationStartService(db=db, redis=redis).validate_execution_reference(
            simulation_id=simulation_id, workspace_id=workspace_id, network_id=intent.network_id,
            intent_id=intent_id, actor_id=actor_id, plan_sha256=digest(plan.model_dump(mode="json")),
            network_state_sha256=current_network_state_hash(binding=binding, snapshot=snapshot))
    request_hash = digest({"intent_id": str(intent_id), "workspace_id": str(workspace_id),
                           "actor_id": actor_id, "manual_approval": manual_approval,
                           "intent": intent.intent_payload,
                           **({"simulation_id": str(simulation_id)} if simulation_id else {})})
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
        if existing[0].simulation_evidence != simulation_evidence:
            raise HTTPException(409, detail={"code": "INTENT_IDEMPOTENCY_CONFLICT", "message": "Approved simulation evidence changed."})
        accepted = existing[0].command if isinstance(existing[0].command, dict) else {}
        if approval_binding is not None and not approval_binding_matches(
                approval_binding, plan_hash=accepted.get("plan_hash"),
                binding_digest=accepted.get("binding_digest"), run_id=accepted.get("run_id")):
            raise _approval_mismatch()
        await db.commit()
        return intent, True
    if intent.status != "validated":
        raise HTTPException(409, detail={"code": "INTENT_NOT_EXECUTABLE", "message": "Validated intent required."})
    if manual_approval is not True:
        raise HTTPException(409, detail={"code": "MANUAL_APPROVAL_REQUIRED", "message": "Explicit manual lab approval required."})
    if require_distinct_approver() and str(actor_id) == str(intent.requested_by_user_id):
        # ADR-028 four-eyes rule: the approver of a new manual lab change is not its
        # requester. (A replay above returns the existing approval unchanged.)
        raise HTTPException(409, detail={"code": "DISTINCT_APPROVER_REQUIRED",
            "message": "Manual lab execution must be approved by a user other than the intent's requester."})
    if simulation_id is None and is_high_impact(intent):
        # ADR-028 C18 / constitution §2: simulation precedes high-impact execution.
        raise HTTPException(409, detail={"code": "SIMULATION_REQUIRED",
            "message": "High-impact manual lab actions require a completed, passing simulation of this network "
                       "bound to the intent's simulation_action_binding."})
    settings = get_settings()
    try:
        Mailbox(settings)
        plan, binding, snapshot = prepared or await prepare_plan(settings=settings, db=db, redis=redis,
            workspace_id=workspace_id, network_id=intent.network_id, actor_id=actor_id, payload=intent.intent_payload)
    except (ValueError, OSError, ImportError) as exc:
        raise HTTPException(409, detail={"code": "LAB_PRECONDITION_FAILED", "message": "Lab plan, binding, authority or observation unavailable."}) from exc
    plan_hash, binding_digest = digest(plan.model_dump(mode="json")), digest(binding.model_dump(mode="json"))
    if not approval_binding_matches(approval_binding, plan_hash=plan_hash, binding_digest=binding_digest,
                                    run_id=snapshot.run_id):
        raise _approval_mismatch()
    now = datetime.now(UTC)
    command = PendingLabCommand(version=1, execution_id=uuid.uuid4(), run_id=snapshot.run_id,
        binding_digest=binding_digest, plan_hash=plan_hash,
        fence=1, deadline=now + timedelta(seconds=settings.EMULATION_EXECUTION_TIMEOUT_SECONDS), operation="execute", plan=plan)
    job = IntentExecution(execution_id=command.execution_id, intent_id=intent_id, workspace_id=workspace_id,
        org_id=workspace.org_id, outbox_sequence=0,
        request_key=key, request_hash=request_hash, lab_key=binding.topology_id,
        actor_id=actor_id, approved_at=now, command=command.model_dump(mode="json"),
        simulation_evidence=copy.deepcopy(simulation_evidence),
        phase="accepted", blocks_lab=True, cancel_requested=False, fence=0)
    intent.correlation_id = correlation_id
    if stored_key is None:
        intent.idempotency_key = key
    db.add(job)
    try:
        await db.flush()
        _enqueue_pending_validated_event(db, intent, job, workspace.org_id)
        project_execution(intent, job, event=True, db=db)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, detail={"code": "LAB_EXECUTION_CONFLICT", "message": "Request already used or lab has an unresolved execution."}) from exc
    return intent, False
