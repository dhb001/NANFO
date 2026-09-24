"""ADR-012 scope, current authority, readiness, control and stop transactions."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.dependencies import get_claim_org_scope, get_claim_workspace_scope
from app.core.logging import get_logger
from app.db.postgres import AsyncSessionLocal
from app.modules.autonomy import governance
from app.modules.autonomy.providers import Providers, cached_providers, shared_providers, stop_recovery
from app.modules.autonomy.repository import AutonomyRepository, StopLockTimeout
from app.modules.autonomy.schemas import (
    AutonomyResponse,
    DecisionResponse,
    DecisionSummary,
    ExecutionReference,
    ProviderStatus,
    ProviderStatuses,
    Qualification,
    Verification,
)
from app.modules.identity.service import AuthService
from app.modules.network.service import NetworkService
from app.modules.autonomy.models import AutonomyControl, AutonomyDecision, TimedOverride
from app.modules.autonomy.execution_models import AutonomousExecution, AutonomousObservation, AutonomousProviderState
from app.modules.telemetry.references import evidence_item, install_owner_guard, page_position, reference_page

logger = get_logger(__name__)


def autonomy_telemetry_references(row):
    if isinstance(row, AutonomyControl):
        return evidence_item(identity=f"autonomy-control:{row.network_id}", network_id=row.network_id,
                             fields={"last_observation": row.last_observation})
    for model, key, fields in (
        (TimedOverride, "override_id", ("recovery_reference", "verification")),
        (AutonomousObservation, "observation_sha256", ("observation", "safety_observation")),
        (AutonomousExecution, "execution_id", ("command", "prepared", "result")),
        (AutonomousProviderState, "network_id", ("state", "evidence")),
    ):
        if isinstance(row, model):
            return evidence_item(identity=f"{model.__tablename__}:{getattr(row, key)}", network_id=row.network_id,
                                 fields={name: getattr(row, name) for name in fields})
    if row.decision_id is None:
        import uuid

        row.decision_id = uuid.uuid4()
    return evidence_item(identity=f"autonomy-decision:{row.decision_id}", network_id=row.network_id,
        fields={name: getattr(row, name) for name in (
            "observation", "proposal", "safety", "evidence", "verification", "authorization")})


# Worker imports this service before any ORM flush. This covers worker acceptance,
# finish and reconciliation without changing provider/runtime/executor ownership.
install_owner_guard(AutonomyControl, owner="autonomy", extractor=autonomy_telemetry_references,
    fields=("last_observation", "workspace_id", "network_id"))
install_owner_guard(AutonomyDecision, owner="autonomy", extractor=autonomy_telemetry_references,
    fields=("observation", "proposal", "safety", "evidence", "verification", "authorization", "workspace_id", "network_id"))
for _model, _fields in (
    (TimedOverride, ("recovery_reference", "verification")),
    (AutonomousObservation, ("observation", "safety_observation")),
    (AutonomousExecution, ("command", "prepared", "result")),
    (AutonomousProviderState, ("state", "evidence")),
):
    install_owner_guard(_model, owner="autonomy", extractor=autonomy_telemetry_references,
                        fields=(*_fields, "workspace_id", "network_id"))


async def telemetry_reference_page(db, *, workspace_id, after=None, limit=100):
    """Internal keyset contract over every decision plus retained control observation."""
    import json
    from sqlalchemy import func, select
    from app.modules.autonomy.experimental.models import LabAction, LabReceipt, LabRun
    from app.modules.autonomy.experimental.references import historical_reference, reference_rows

    # v2 appends0028 stages. Legacy cursors restart at the oldest formal stage,
    # rather than silently skipping history after a deployment/coverage reset.
    cursor = json.loads(after) if after else None
    if isinstance(cursor, dict):
        if set(cursor) != {"version", "position"} or cursor["version"] != 2:
            raise ValueError("invalid autonomy reference cursor")
        position = json.dumps(cursor["position"])
    else:
        if after:
            page_position(after, stages=6, limit=limit, text_key=True)
        position = None
    stages = 9
    stage, last = page_position(position, stages=stages, limit=limit, text_key=True)

    def versioned(page):
        if page.next_cursor is not None:
            page.next_cursor = json.dumps({"version": 2, "position": json.loads(page.next_cursor)})
        return page

    model, key = ((AutonomyControl, AutonomyControl.network_id),
                  (AutonomyDecision, AutonomyDecision.decision_id),
                  (TimedOverride, TimedOverride.override_id),
                  (AutonomousObservation, AutonomousObservation.observation_sha256),
                  (AutonomousExecution, AutonomousExecution.execution_id),
                  (AutonomousProviderState, AutonomousProviderState.network_id),
                  (LabRun, LabRun.run_id), (LabAction, LabAction.request_id),
                  (LabReceipt, LabReceipt.receipt_id))[stage]
    if stage >= 3 and await db.scalar(select(func.to_regclass(model.__tablename__))) is None:
        #0025 is independently deployable before optional Autonomy runtime0027.
        return versioned(reference_page([], extractor=autonomy_telemetry_references,
                              key=lambda row: None, limit=limit, stage=stage, stages=stages))
    if stage >= 6:
        rows = await reference_rows(db, model, key, workspace_id=workspace_id, last=last, limit=limit)
        return versioned(reference_page(rows, extractor=historical_reference,
            key=lambda row: getattr(row[0], key.key), limit=limit, stage=stage, stages=stages))
    query = select(model).where(model.workspace_id == workspace_id)
    if last:
        if stage != 3:
            from uuid import UUID

            last = UUID(last)
        query = query.where(key > last)
    rows = list((await db.scalars(query.order_by(key).limit(limit + 1))).all())
    return versioned(reference_page(rows, extractor=autonomy_telemetry_references,
                          key=lambda row: getattr(row, key.key), limit=limit, stage=stage, stages=stages))

WRITE_PERMISSIONS = {"write:config", "execute:rollback"}
MAX_APPROVAL_SECONDS = 3600
PROVIDER_TIMEOUT_SECONDS = 5


async def authorize(*, db, redis, network_id, actor_id, write, workspace_id=None, org_id=None):
    profile = await AuthService(db, redis).get_profile(actor_id)
    required = WRITE_PERMISSIONS if write else {"read:telemetry"}
    if not required.issubset(profile.permissions):
        raise HTTPException(403, detail="Insufficient permissions.")
    network = await NetworkService(db=db, redis=redis).assert_network_workspace_access(
        network_id=network_id, requested_workspace_id=workspace_id, actor_user_id=actor_id,
        claim_org_id=org_id, require_write=write,
    )
    return network, profile.permissions


def approval_reasons(control, now=None):
    now = now or datetime.now(UTC)
    reasons = []
    if control.emergency_stopped:
        reasons.append("emergency_stop_latched")
    if control.active_execution_id is not None or control.cancellation_status in {"requested", "uncertain"}:
        reasons.append("execution_unresolved")
    if control.mode == "autonomous" and (
        not control.approved_by_user_id or not control.approval_expires_at or control.approval_expires_at <= now
    ):
        reasons.append("approval_expired_or_missing")
    return reasons


async def readiness(providers: Providers, checkpoint_sha256, *, production=False, require_executor=True):
    refresh = getattr(providers.executor, "refresh_status", None)
    if require_executor and refresh is not None:
        async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
            await refresh()
    statuses = providers.statuses()
    reasons = [reason for status in (
        statuses.observer, statuses.qualification, statuses.inference,
        *([statuses.safety, statuses.executor] if require_executor else []),
    ) if status.status != "ready" for reason in (status.reasons or [f"{status.provider_id}_unavailable"])]
    if production and require_executor:
        reasons.append("production_dispatch_disabled")
    async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
        qualification = Qualification.model_validate(await providers.model.qualify(checkpoint_sha256))
    if (not checkpoint_sha256 or not qualification.qualified or qualification.checkpoint_sha256 != checkpoint_sha256
            or not qualification.manifest_sha256 or not qualification.observation_contract or not qualification.evidence):
        reasons.extend(qualification.reasons or ["qualified_checkpoint_unavailable"])
    return list(dict.fromkeys(reasons)), qualification


class AutonomyService:
    def __init__(self, db, redis, *, providers=None, sessions=AsyncSessionLocal):
        self.db, self.redis = db, redis
        self.repo = AutonomyRepository(db)
        self.providers = providers or installed_providers(sessions, redis)

    async def scope(self, claims, network_id, *, write=False):
        return await authorize(db=self.db, redis=self.redis, network_id=network_id, actor_id=claims.user_id,
            write=write, workspace_id=get_claim_workspace_scope(claims=claims), org_id=get_claim_org_scope(claims=claims))

    async def get(self, *, claims, network_id, history_limit=20):
        network, _ = await self.scope(claims, network_id)
        return await self.snapshot(network_id, network.workspace_id, history_limit=history_limit)

    async def snapshot(self, network_id, workspace_id, *, history_limit=20):
        control = await self.repo.get(network_id)
        decisions = [DecisionResponse.model_validate(row) for row in await self.repo.history(network_id, history_limit)]
        try:
            reasons, _ = await readiness(self.providers, control.checkpoint_sha256 if control else None,
                                        production=get_settings().EXECUTION_MODE == "production")
        except Exception:  # noqa: BLE001 - unavailable providers are explicit, never optimistic
            reasons = ["provider_readiness_failed"]
        if control:
            if control.workspace_id != workspace_id:
                raise HTTPException(409, detail="Network ownership changed; autonomy reconciliation required.")
            reasons.extend(approval_reasons(control))
            if await self.repo.unresolved_override(network_id):
                reasons.append("timed_override_unresolved")
            if control.active_execution_id and decisions:
                reasons.extend(decisions[0].reasons)
            if control.mode == "autonomous" and control.approved_by_user_id:
                try:
                    await authorize(db=self.db, redis=self.redis, network_id=network_id,
                        workspace_id=workspace_id, actor_id=control.approved_by_user_id, write=True)
                except HTTPException:
                    reasons.append("approval_actor_unauthorized")
        reasons = list(dict.fromkeys(reasons))
        mode = control.mode if control else "monitor"
        state = "monitoring" if mode == "monitor" else ("blocked" if reasons else "ready")
        if control and control.active_execution_id:
            state = "executing"
        if control and control.emergency_stopped:
            state = "stopped"
        if control and control.cancellation_status == "uncertain":
            state = "uncertain"
        return AutonomyResponse(
            network_id=network_id, workspace_id=workspace_id, mode=mode, status=state, ready=not reasons,
            blocked_reasons=reasons, checkpoint_sha256=control.checkpoint_sha256 if control else None,
            approval_expires_at=control.approval_expires_at if control else None,
            approved_by_user_id=control.approved_by_user_id if control else None,
            emergency_stopped=control.emergency_stopped if control else False,
            stopped_at=control.stopped_at if control else None,
            stopped_by_user_id=control.stopped_by_user_id if control else None,
            active_execution_id=control.active_execution_id if control else None,
            cancellation_status=control.cancellation_status if control else "none",
            revision=control.revision if control else 0, providers=self.providers.statuses(),
            last_observation=control.last_observation if control else None,
            last_decision=decisions[0] if decisions else None, decisions=decisions,
            history_limit=history_limit, updated_at=control.updated_at if control else None,
        )

    async def set_mode(self, *, claims, request):
        network, _ = await self.scope(claims, request.network_id, write=True)
        workspace_id = network.workspace_id
        existing = await self.repo.get(request.network_id)
        initial_revision = existing.revision if existing else 0
        if initial_revision != request.expected_revision:
            await self.db.rollback()
            raise HTTPException(409, detail={"code": "AUTONOMY_REVISION_CONFLICT", "message": "Control changed; refresh before changing mode."})
        # Qualification can perform bounded read-only I/O, never while holding a control lock.
        await self.db.commit()
        now = datetime.now(UTC)
        if request.mode == "autonomous":
            try:
                reasons, _ = await readiness(self.providers, request.checkpoint_sha256,
                                            production=get_settings().EXECUTION_MODE == "production")
            except Exception:  # noqa: BLE001
                reasons = ["provider_readiness_failed"]
            if not request.approval_expires_at or not now < request.approval_expires_at <= now + timedelta(seconds=MAX_APPROVAL_SECONDS):
                reasons.append("approval_expiry_invalid")
            if reasons:
                raise HTTPException(409, detail={"code": "AUTONOMY_NOT_READY", "message": ", ".join(reasons)})
        # Revalidate after provider wait; control writes invalidate in-flight cycle fences.
        network, _ = await self.scope(claims, request.network_id, write=True)
        if network.workspace_id != workspace_id:
            await self.db.rollback()
            raise HTTPException(409, detail="Network ownership changed; autonomy reconciliation required.")
        control = await self.repo.ensure(request.network_id, workspace_id)
        if control.revision != initial_revision or control.revision != request.expected_revision:
            await self.db.rollback()
            raise HTTPException(409, detail={"code": "AUTONOMY_REVISION_CONFLICT", "message": "Control changed; refresh before changing mode."})
        if (control.workspace_id != workspace_id or control.active_execution_id or control.cancellation_status in {"requested", "uncertain"}
                or await self.repo.unresolved_override(request.network_id)):
            await self.db.rollback()
            raise HTTPException(409, detail={"code": "AUTONOMY_UNRESOLVED", "message": "Owned execution requires verified reconciliation."})
        if request.mode == "autonomous" and request.approval_expires_at <= datetime.now(UTC):
            await self.db.rollback()
            raise HTTPException(409, detail={"code": "AUTONOMY_NOT_READY", "message": "approval_expired_or_missing"})
        control.mode, control.checkpoint_sha256 = request.mode, request.checkpoint_sha256
        control.approval_expires_at = request.approval_expires_at if request.mode == "autonomous" else None
        control.approved_by_user_id = claims.user_id
        control.emergency_stopped, control.stopped_at, control.stopped_by_user_id = False, None, None
        control.cancellation_status = "none"
        control.revision += 1
        control.claim_token, control.lease_expires_at = None, None
        control.updated_at = datetime.now(UTC)
        await self.repo.invalidate_observing(control.network_id, "control_changed_before_acceptance")
        self.repo.record(control, status="control_changed", reasons=["explicit_mode_change"], actor_id=claims.user_id)
        await self.db.commit()
        return await self.snapshot(request.network_id, workspace_id)

    async def stop(self, *, claims, network_id):
        network, permissions = await self.scope(claims, network_id, write=True)
        workspace_id = network.workspace_id
        control = await self.repo.ensure(network_id, workspace_id)
        if control.workspace_id != workspace_id:
            await self.db.rollback()
            raise HTTPException(409, detail="Network ownership changed; autonomy reconciliation required.")
        control.emergency_stopped = True
        control.stopped_at, control.updated_at = datetime.now(UTC), datetime.now(UTC)
        control.stopped_by_user_id = claims.user_id
        control.revision += 1
        control.claim_token, control.lease_expires_at = None, None
        execution_id, intent_id = control.active_execution_id, control.active_intent_id
        stop_revision = control.revision
        if execution_id:
            control.cancellation_status = "requested"
        await self.repo.invalidate_observing(control.network_id, "emergency_stop_latched")
        decision = self.repo.record(control, status="stopped", reasons=["emergency_stop_latched"], actor_id=claims.user_id)
        decision.execution_id = execution_id
        # The latch survives process death, cancellation failure and API timeout.
        await self.db.commit()
        if execution_id:
            try:
                async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
                    result = Verification.model_validate(await self.providers.cancellation.cancel(
                        network_id=network_id, workspace_id=workspace_id, intent_id=intent_id,
                        execution_id=execution_id, actor_id=claims.user_id, permissions=permissions,
                    ))
                if result.execution_id != execution_id:
                    raise ValueError("cancellation identity mismatch")
            except Exception:  # noqa: BLE001 - unknown cancellation never releases exclusion
                result = Verification(execution_id=execution_id, status="uncertain", reasons=["cancellation_failed"])
            control = await self.repo.get(network_id, lock=True)
            decision = await self.repo.decision(decision.decision_id)
            decision.verification = result.model_dump(mode="json")
            decision.reasons = list(dict.fromkeys([*decision.reasons, *result.reasons]))
            if control.active_execution_id == execution_id and control.revision == stop_revision:
                if result.status == "cancelled" and result.safe_to_release and result.evidence:
                    control.active_execution_id, control.active_intent_id, control.active_decision_id = None, None, None
                    control.cancellation_status = "verified"
                else:
                    control.cancellation_status = "uncertain" if result.status == "uncertain" else "requested"
            await self.db.commit()
        return await self.snapshot(network_id, workspace_id)
