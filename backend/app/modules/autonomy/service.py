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


#: Formal (non-experimental) reference stages, in cursor order.
_FORMAL_STAGES = (
    (AutonomyControl, AutonomyControl.network_id),
    (AutonomyDecision, AutonomyDecision.decision_id),
    (TimedOverride, TimedOverride.override_id),
    (AutonomousObservation, AutonomousObservation.observation_sha256),
    (AutonomousExecution, AutonomousExecution.execution_id),
    (AutonomousProviderState, AutonomousProviderState.network_id),
)


def _experimental_stage(stage):
    """Historical experimental-lab rows (migration 0028 tables), imported only when enumerated.

    Deliberately NOT gated by NANFO_EXPERIMENTAL_LAB_ENABLED: rows written while the lab was
    enabled keep pinning telemetry evidence, so retention must still enumerate them after the
    lab is switched off (ADR-023 "unknown historical coverage stays retained").
    """
    from app.modules.autonomy.experimental.models import LabAction, LabReceipt, LabRun

    return ((LabRun, LabRun.run_id), (LabAction, LabAction.request_id),
            (LabReceipt, LabReceipt.receipt_id))[stage - len(_FORMAL_STAGES)]


async def telemetry_reference_page(db, *, workspace_id, after=None, limit=100):
    """Internal keyset contract over every decision plus retained control observation."""
    import json
    from sqlalchemy import func, select

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

    model, key = _FORMAL_STAGES[stage] if stage < len(_FORMAL_STAGES) else _experimental_stage(stage)
    if stage >= 3 and await db.scalar(select(func.to_regclass(model.__tablename__))) is None:
        #0025 is independently deployable before optional Autonomy runtime0027.
        return versioned(reference_page([], extractor=autonomy_telemetry_references,
                              key=lambda row: None, limit=limit, stage=stage, stages=stages))
    if stage >= 6:
        from app.modules.autonomy.experimental.references import historical_reference, reference_rows

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
#: STOP latch attempts, each bounded by repository.STOP_LOCK_TIMEOUT_MS (fix 1).
STOP_LOCK_ATTEMPTS = 3
#: Reported for providers when a response is built without constructing them (STOP).
PROVIDER_NOT_EVALUATED = ProviderStatus(provider_id="not_evaluated", status="unavailable",
                                        reasons=["provider_status_not_evaluated"])


def _conflict(code, message):
    return HTTPException(409, detail={"code": code, "message": message})


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


async def authorize_stop(*, db, redis, network_id, actor_id, workspace_id=None, org_id=None, control=None):
    """STOP authority (C25, ADR-028 fix 5); returns (control workspace id, permissions).

    With AUTONOMY_STOP_ALLOW_READ_ONLY (default) any current org member holding
    ``read:telemetry`` may STOP (no write fences are taken); otherwise the ordinary write
    authority applies. STOP of a soft-deleted network is authorized against the control
    row's own workspace through the Organization service (Network hides deleted rows).
    """
    write = not governance.stop_allows_read_only()
    try:
        network, permissions = await authorize(db=db, redis=redis, network_id=network_id, actor_id=actor_id,
                                               write=write, workspace_id=workspace_id, org_id=org_id)
    except HTTPException as exc:
        if exc.status_code != 404 or control is None:
            raise
        return control.workspace_id, await _authorize_stop_by_control_scope(
            db=db, redis=redis, actor_id=actor_id, write=write, control=control,
            claim_workspace_id=workspace_id, claim_org_id=org_id)
    if control is not None and control.workspace_id != network.workspace_id:
        raise HTTPException(409, detail="Network ownership changed; autonomy reconciliation required.")
    return network.workspace_id, permissions


async def _authorize_stop_by_control_scope(*, db, redis, actor_id, write, control, claim_workspace_id, claim_org_id):
    from app.modules.organization.service import WorkspaceService

    profile = await AuthService(db, redis).get_profile(actor_id)
    if not (WRITE_PERMISSIONS if write else {"read:telemetry"}).issubset(profile.permissions):
        raise HTTPException(403, detail="Insufficient permissions.")
    if claim_workspace_id is not None and claim_workspace_id != control.workspace_id:
        raise HTTPException(403, detail="Insufficient permissions.")
    workspaces = WorkspaceService(db=db, redis=redis)
    if write:
        workspace = await workspaces.check_workspace_write_authority(control.workspace_id, user_id=actor_id)
    else:
        workspace = await workspaces.assert_workspace_membership(workspace_id=control.workspace_id, user_id=actor_id)
    if claim_org_id is not None and workspace.org_id != claim_org_id:
        raise HTTPException(403, detail="Insufficient permissions.")
    return profile.permissions


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
        self.db, self.redis, self.sessions = db, redis, sessions
        self.repo = AutonomyRepository(db)
        self._providers = providers
        #: PendingApproval recorded by the last set_mode call instead of switching (C25), else None.
        self.recorded_pending_approval = None

    @property
    def providers(self) -> Providers:
        # Synchronous fallback; request paths call ``get_providers`` (off-loop construction).
        if self._providers is None:
            self._providers = shared_providers(self.sessions, self.redis)
        return self._providers

    @providers.setter
    def providers(self, value):
        self._providers = value

    async def get_providers(self) -> Providers:
        """Process-cached providers; a cache miss is built in a worker thread (fix 1)."""
        if self._providers is None:
            cached = cached_providers(self.sessions, self.redis)
            self._providers = cached if cached is not None else await asyncio.to_thread(
                shared_providers, self.sessions, self.redis)
        return self._providers

    async def scope(self, claims, network_id, *, write=False):
        return await authorize(db=self.db, redis=self.redis, network_id=network_id, actor_id=claims.user_id,
            write=write, workspace_id=get_claim_workspace_scope(claims=claims), org_id=get_claim_org_scope(claims=claims))

    async def get(self, *, claims, network_id, history_limit=20):
        network, _ = await self.scope(claims, network_id)
        return await self.snapshot(network_id, network.workspace_id, history_limit=history_limit)

    async def pending_approval(self, network_id, control):
        """Current (revision-bound) C25 pending request, if any; stale requests are ignored."""
        try:
            pending = await governance.read_pending(self.redis, network_id)
        except Exception:  # noqa: BLE001 - absent Redis never fabricates or hides a mode change
            return None
        if pending is None or pending.approval.expected_revision != (control.revision if control else 0):
            return None
        if control is not None and pending.workspace_id != control.workspace_id:
            return None
        return pending

    async def snapshot(self, network_id, workspace_id, *, history_limit=20, evaluate_providers=True):
        control = await self.repo.get(network_id, fresh=True)
        latest = await self.repo.history(network_id, 1)
        last_decision = DecisionResponse.model_validate(latest[0]) if latest else None
        # Lists are server-side summaries: no observation samples, bound inputs or authorization blobs.
        decisions = [DecisionSummary.model_validate(row)
                     for row in await self.repo.history(network_id, history_limit, summary=True)]
        providers = None
        if evaluate_providers:
            providers = await self.get_providers()
            try:
                reasons, _ = await readiness(providers, control.checkpoint_sha256 if control else None,
                                            production=get_settings().EXECUTION_MODE == "production")
            except Exception:  # noqa: BLE001 - unavailable providers are explicit, never optimistic
                reasons = ["provider_readiness_failed"]
        else:
            # STOP responses never construct providers; reuse an existing composition if any.
            providers = self._providers or cached_providers(self.sessions, self.redis)
            reasons = [] if providers is not None else ["provider_status_not_evaluated"]
        if control:
            if control.workspace_id != workspace_id:
                raise HTTPException(409, detail="Network ownership changed; autonomy reconciliation required.")
            reasons.extend(approval_reasons(control))
            if await self.repo.unresolved_override(network_id):
                reasons.append("timed_override_unresolved")
            if control.active_execution_id and last_decision:
                reasons.extend(last_decision.reasons)
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
        pending = await self.pending_approval(network_id, control)
        statuses = providers.statuses() if providers is not None else ProviderStatuses(
            observer=PROVIDER_NOT_EVALUATED, qualification=PROVIDER_NOT_EVALUATED,
            inference=PROVIDER_NOT_EVALUATED, safety=PROVIDER_NOT_EVALUATED, executor=PROVIDER_NOT_EVALUATED)
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
            revision=control.revision if control else 0, providers=statuses,
            last_observation=control.last_observation if control else None,
            last_decision=last_decision, decisions=decisions,
            history_limit=history_limit, updated_at=control.updated_at if control else None,
            pending_approval=pending.approval if pending else None,
        )

    async def set_mode(self, *, claims, request, correlation_id=None):
        self.recorded_pending_approval = None
        network, _ = await self.scope(claims, request.network_id, write=True)
        workspace_id = network.workspace_id
        existing = await self.repo.get(request.network_id)
        initial_revision = existing.revision if existing else 0
        if initial_revision != request.expected_revision:
            await self.db.rollback()
            raise _conflict("AUTONOMY_REVISION_CONFLICT", "Control changed; refresh before changing mode.")
        # Qualification can perform bounded read-only I/O, never while holding a control lock.
        await self.db.commit()
        now = datetime.now(UTC)
        pending = None
        if request.mode == "autonomous":
            providers = await self.get_providers()
            try:
                reasons, _ = await readiness(providers, request.checkpoint_sha256,
                                            production=get_settings().EXECUTION_MODE == "production")
            except Exception:  # noqa: BLE001
                reasons = ["provider_readiness_failed"]
            if not request.approval_expires_at or not now < request.approval_expires_at <= now + timedelta(seconds=MAX_APPROVAL_SECONDS):
                reasons.append("approval_expiry_invalid")
            if reasons:
                raise _conflict("AUTONOMY_NOT_READY", ", ".join(reasons))
            if governance.require_distinct_approver():
                # C25 four-eyes: the first request is recorded; a different user's identical PUT confirms.
                pending = await governance.read_pending(self.redis, request.network_id)
                if (pending is None or pending.fingerprint != governance.request_fingerprint(request)
                        or pending.workspace_id != workspace_id):
                    return await self._record_pending(claims, request, workspace_id, correlation_id)
                if pending.approval.requested_by_user_id == claims.user_id:
                    raise _conflict("AUTONOMY_DISTINCT_APPROVER_REQUIRED",
                                    "A different authorized user must confirm the autonomous request.")
        # Revalidate after provider wait; control writes invalidate in-flight cycle fences.
        network, _ = await self.scope(claims, request.network_id, write=True)
        if network.workspace_id != workspace_id:
            await self.db.rollback()
            raise HTTPException(409, detail="Network ownership changed; autonomy reconciliation required.")
        control = await self.repo.ensure(request.network_id, workspace_id)
        if control.revision != initial_revision or control.revision != request.expected_revision:
            await self.db.rollback()
            raise _conflict("AUTONOMY_REVISION_CONFLICT", "Control changed; refresh before changing mode.")
        if (control.workspace_id != workspace_id or control.active_execution_id or control.cancellation_status in {"requested", "uncertain"}
                or await self.repo.unresolved_override(request.network_id)):
            await self.db.rollback()
            raise _conflict("AUTONOMY_UNRESOLVED", "Owned execution requires verified reconciliation.")
        if request.mode == "autonomous" and request.approval_expires_at <= datetime.now(UTC):
            await self.db.rollback()
            raise _conflict("AUTONOMY_NOT_READY", "approval_expired_or_missing")
        cleared_stop = bool(control.emergency_stopped)
        if cleared_stop:
            # C25: clearing an emergency STOP requires the caller's *current* org role Admin.
            role = await governance.caller_org_role(self.db, self.redis, workspace_id=workspace_id,
                                                    user_id=claims.user_id)
            if role != "Admin":
                await self.db.rollback()
                raise HTTPException(403, detail={"code": "AUTONOMY_STOP_CLEAR_REQUIRES_ADMIN",
                                                 "message": "Only an organization Admin can clear an emergency stop."})
        previous_mode = control.mode
        control.mode, control.checkpoint_sha256 = request.mode, request.checkpoint_sha256
        control.approval_expires_at = request.approval_expires_at if request.mode == "autonomous" else None
        control.approved_by_user_id = claims.user_id
        control.emergency_stopped, control.stopped_at, control.stopped_by_user_id = False, None, None
        control.cancellation_status = "none"
        control.revision += 1
        control.claim_token, control.lease_expires_at = None, None
        control.updated_at = datetime.now(UTC)
        await self.repo.invalidate_observing(control.network_id, "control_changed_before_acceptance")
        decision = self.repo.record(control, status="control_changed", reasons=["explicit_mode_change"], actor_id=claims.user_id)
        if pending is not None:
            decision.reasons = ["explicit_mode_change", "two_person_approval_confirmed"]
        await governance.audit(self.db, self.redis, event_type="autonomy.mode.changed", actor_id=claims.user_id,
            network_id=request.network_id, workspace_id=workspace_id, correlation_id=correlation_id, metadata={
                "from_mode": previous_mode, "to_mode": request.mode, "revision": control.revision,
                "checkpoint_sha256": request.checkpoint_sha256,
                "approval_expires_at": request.approval_expires_at.isoformat() if request.approval_expires_at else None,
                "requested_by_user_id": pending.approval.requested_by_user_id if pending else claims.user_id,
                "confirmed_by_user_id": claims.user_id, "two_person": pending is not None,
                "cleared_emergency_stop": cleared_stop})
        await self.db.commit()
        if pending is not None:
            await governance.consume_pending(self.redis, request.network_id, pending)
        return await self.snapshot(request.network_id, workspace_id)

    async def _record_pending(self, claims, request, workspace_id, correlation_id):
        pending = await governance.record_pending(self.redis, request=request, workspace_id=workspace_id,
                                                  actor_id=claims.user_id, correlation_id=correlation_id)
        await governance.audit(self.db, self.redis, event_type="autonomy.mode.approval_requested",
            actor_id=claims.user_id, network_id=request.network_id, workspace_id=workspace_id,
            correlation_id=correlation_id, metadata={
                "to_mode": request.mode, "expected_revision": request.expected_revision,
                "checkpoint_sha256": request.checkpoint_sha256,
                "approval_expires_at": request.approval_expires_at.isoformat() if request.approval_expires_at else None,
                "pending_expires_at": pending.approval.expires_at.isoformat()})
        await self.db.commit()
        self.recorded_pending_approval = pending.approval
        return await self.snapshot(request.network_id, workspace_id)

    async def stop(self, *, claims, network_id, correlation_id=None):
        """Latch STOP in one short provider-independent transaction, then cancel owned work."""
        control = await self.repo.get(network_id)
        workspace_id, _ = await authorize_stop(db=self.db, redis=self.redis, network_id=network_id,
            actor_id=claims.user_id, workspace_id=get_claim_workspace_scope(claims=claims),
            org_id=get_claim_org_scope(claims=claims), control=control)
        latched = None
        for attempt in range(STOP_LOCK_ATTEMPTS):
            try:
                latched = await self.repo.latch_stop(network_id=network_id, workspace_id=workspace_id,
                                                     actor_id=claims.user_id)
                break
            except StopLockTimeout:
                await self.db.rollback()
                if attempt + 1 == STOP_LOCK_ATTEMPTS:
                    raise HTTPException(503, detail={
                        "code": "AUTONOMY_STOP_BUSY",
                        "message": "Emergency stop could not be latched within its lock timeout; retry now.",
                    }, headers={"Retry-After": "1"}) from None
                await asyncio.sleep(0.05 * (attempt + 1))
        if latched is None:
            await self.db.rollback()
            raise HTTPException(409, detail="Network ownership changed; autonomy reconciliation required.")
        await self.repo.invalidate_observing(network_id, "emergency_stop_latched")
        decision = self.repo.record(latched, status="stopped", reasons=["emergency_stop_latched"], actor_id=claims.user_id)
        decision.execution_id = latched.active_execution_id
        await governance.audit(self.db, self.redis, event_type="autonomy.stop.latched", actor_id=claims.user_id,
            network_id=network_id, workspace_id=workspace_id, correlation_id=correlation_id, metadata={
                "revision": latched.revision, "cancellation_status": latched.cancellation_status,
                "execution_id": str(latched.active_execution_id) if latched.active_execution_id else None})
        # The latch survives process death, cancellation failure and API timeout.
        await self.db.commit()
        await governance.discard_pending(self.redis, network_id)
        if latched.active_execution_id:
            await self._cancel_owned_execution(latched, decision.decision_id)
        return await self.snapshot(network_id, workspace_id, evaluate_providers=False)

    async def _cancel_owned_execution(self, latched, decision_id):
        """Exact persisted Autonomy execution only, via the recovery provider (never Intent)."""
        execution_id = latched.active_execution_id
        recovery = self._providers.recovery if self._providers is not None else stop_recovery(self.sessions)
        reference = ExecutionReference(network_id=latched.network_id, workspace_id=latched.workspace_id,
            intent_id=latched.active_intent_id, execution_id=execution_id, decision_id=latched.active_decision_id,
            # Recovery verifies persisted identity only; this token is not a cycle capability.
            control_revision=latched.revision, claim_token=uuid.uuid4())
        try:
            async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
                result = Verification.model_validate(await recovery.cancel(reference))
            if result.execution_id != execution_id:
                raise ValueError("cancellation identity mismatch")
        except Exception:  # noqa: BLE001 - unknown cancellation never releases exclusion
            result = Verification(execution_id=execution_id, status="uncertain", reasons=["cancellation_failed"])
        if result.status == "cancelled" and result.safe_to_release and result.evidence:
            status = "verified"
        else:
            status = "uncertain" if result.status == "uncertain" else "requested"
        try:
            decision = await self.repo.decision(decision_id)
            decision.verification = result.model_dump(mode="json")
            decision.reasons = list(dict.fromkeys([*decision.reasons, *result.reasons]))
            await self.repo.settle_stop_cancellation(network_id=latched.network_id, execution_id=execution_id,
                                                     stop_revision=latched.revision, status=status)
            await self.db.commit()
        except StopLockTimeout:
            # The worker reconciles the owned execution immediately (next_cycle_at = STOP time).
            await self.db.rollback()
