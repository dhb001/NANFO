"""Persistent timed holds, exact-owned restoration and revision-fenced mode return."""

import asyncio
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.runtime_health import worker_iteration
from app.modules.autonomy import governance
from app.modules.autonomy.models import TimedOverride
from app.modules.autonomy.repository import AutonomyRepository
from app.modules.autonomy.schemas import Observation, OverrideListResponse, OverrideResponse
from app.modules.autonomy.service import AutonomyService, authorize, readiness
from app.modules.intent.overrides import IntentOverrideService

logger = get_logger(__name__)


async def verify_override_enrollment(db, reference):
    """Public server-only enrollment proof; never exposes the capability to REST."""
    if not isinstance(reference, dict):
        return False
    try:
        row = await AutonomyRepository(db).override(uuid.UUID(reference["override_id"]))
        return bool(row and row.status == "restoring" and row.cancellation_id == row.execution_id
                    and secrets.compare_digest(str(reference.get("capability", "")), row.recovery_reference["capability"])
                    and reference == row.recovery_reference)
    except (ValueError, KeyError, TypeError):
        return False


class OverrideService(AutonomyService):
    def __init__(self, db, redis, *, intent=None, **kwargs):
        super().__init__(db, redis, **kwargs)
        self.intent = intent or IntentOverrideService(db, redis)

    async def list(self, *, claims, network_id):
        network, _ = await self.scope(claims, network_id)
        control = await self.repo.get(network_id)
        rows = await self.repo.overrides(network_id)
        if (control and control.workspace_id != network.workspace_id) or any(row.workspace_id != network.workspace_id for row in rows):
            raise HTTPException(409, detail="Network ownership changed; reconciliation required.")
        return OverrideListResponse(network_id=network_id, control_revision=control.revision if control else 0,
                                    overrides=[OverrideResponse.model_validate(row) for row in rows])

    async def create(self, *, claims, request, correlation_id=None):
        network, _ = await self.scope(claims, request.network_id, write=True)
        workspace_id = network.workspace_id
        control = await self.repo.get(request.network_id)
        if (control.revision if control else 0) != request.expected_revision:
            raise HTTPException(409, detail="Control revision changed; refresh before enrollment.")
        await self.db.commit()
        override_id = uuid.uuid4()
        try:
            async with asyncio.timeout(5):
                reference = await self.intent.inspect_override_execution(network_id=request.network_id,
                    workspace_id=workspace_id, intent_id=request.intent_id, execution_id=request.execution_id,
                    actor_id=claims.user_id, override_id=override_id)
        except TimeoutError as exc:
            await self.db.rollback()
            raise HTTPException(503, detail="Enrollment evidence temporarily unavailable.") from exc
        # I/O is outside the control lock. Authority and the expected revision are
        # rechecked afterwards, so a concurrent STOP wins over enrollment.
        network, _ = await self.scope(claims, request.network_id, write=True)
        control = await self.repo.ensure(request.network_id, workspace_id)
        if (network.workspace_id != workspace_id or control.workspace_id != workspace_id
                or control.revision != request.expected_revision or control.emergency_stopped
                or control.active_execution_id or control.cancellation_status in {"requested", "uncertain"}
                or await self.repo.unresolved_override(request.network_id)):
            await self.db.rollback()
            raise HTTPException(409, detail="Control changed, stopped or has unresolved execution.")
        await self.intent.validate_override_reference(reference)
        now = datetime.now(UTC)
        verified_at = datetime.fromisoformat(reference["configuration_verified_at"])
        if not 0 <= (now - verified_at).total_seconds() <= 30:
            await self.db.rollback()
            raise HTTPException(409, detail="Enrollment readback expired during authorization.")
        if request.return_mode == "autonomous" and (
            control.mode != "autonomous" or control.approved_by_user_id != claims.user_id
            or not control.checkpoint_sha256 or not control.approval_expires_at
            or control.approval_expires_at <= now + timedelta(seconds=request.duration_seconds)
        ):
            await self.db.rollback()
            raise HTTPException(409, detail="Autonomous return requires this actor's prior model approval valid beyond the override.")
        row = TimedOverride(override_id=override_id, network_id=request.network_id, workspace_id=workspace_id,
            intent_id=request.intent_id, execution_id=request.execution_id, actor_id=claims.user_id, reason=request.reason,
            duration_seconds=request.duration_seconds, return_mode=request.return_mode, prior_mode=control.mode,
            prior_revision=control.revision, hold_revision=control.revision + 1, checkpoint_sha256=control.checkpoint_sha256,
            prior_approval_expires_at=control.approval_expires_at, prior_approved_by_user_id=control.approved_by_user_id,
            command_sha256=reference["command_sha256"], plan_hash=reference["plan_hash"], binding_digest=reference["binding_digest"],
            run_id=uuid.UUID(reference["run_id"]), configuration_verified_at=verified_at, recovery_reference=reference,
            status="holding", reasons=["historical_configuration_readback_not_live_observation"], restoration_attempts=0,
            expires_at=now + timedelta(seconds=request.duration_seconds), next_check_at=now, created_at=now, updated_at=now)
        self.db.add(row)
        control.mode = "monitor"
        control.revision += 1
        control.claim_token, control.lease_expires_at = None, None
        control.updated_at = now
        await self.repo.invalidate_observing(control.network_id, "override_enrolled")
        self.repo.record(control, status="control_changed", reasons=["timed_override_enrolled"], actor_id=claims.user_id)
        await governance.audit(self.db, self.redis, event_type="autonomy.override.created", actor_id=claims.user_id,
            network_id=request.network_id, workspace_id=workspace_id, correlation_id=correlation_id,
            resource_type="autonomy_override", resource_id=override_id, metadata={
                "override_id": str(override_id), "execution_id": str(request.execution_id),
                "intent_id": str(request.intent_id), "duration_seconds": request.duration_seconds,
                "return_mode": request.return_mode, "prior_mode": row.prior_mode, "hold_revision": row.hold_revision,
                "reason": request.reason[:256]})
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(409, detail="Execution already enrolled or another override owns the network.") from exc
        return OverrideResponse.model_validate(row)

    async def scoped_override(self, claims, override_id):
        row = await self.repo.override(override_id)
        if row is None:
            raise HTTPException(404, detail="Override not found.")
        network, _ = await self.scope(claims, row.network_id, write=True)
        if network.workspace_id != row.workspace_id:
            raise HTTPException(409, detail="Network ownership changed; reconciliation required.")
        return row

    async def cancel(self, *, claims, override_id, correlation_id=None):
        row = await self.scoped_override(claims, override_id)
        # All mutators use control -> override lock order.
        await self.repo.get(row.network_id, lock=True)
        row = await self.repo.override(override_id, lock=True)
        if row.status == "holding":
            row.status, row.reasons = "restoring", ["operator_cancel_requested"]
            row.cancellation_id = row.execution_id
            row.cancellation_requested_at = datetime.now(UTC)
            row.cancelled_by_user_id = claims.user_id
            row.next_check_at = row.updated_at = datetime.now(UTC)
            row.claim_token, row.lease_expires_at = None, None
            await governance.audit(self.db, self.redis, event_type="autonomy.override.cancel_requested",
                actor_id=claims.user_id, network_id=row.network_id, workspace_id=row.workspace_id,
                correlation_id=correlation_id, resource_type="autonomy_override", resource_id=row.override_id,
                metadata={"override_id": str(row.override_id), "execution_id": str(row.execution_id)})
        await self.db.commit()
        return OverrideResponse.model_validate(row)

    async def return_mode(self, *, override_id, claims=None, request=None, correlation_id=None):
        row = (await self.scoped_override(claims, override_id) if claims else await self.repo.override(override_id))
        if row is None:
            raise HTTPException(404, detail="Override not found.")
        control = await self.repo.get(row.network_id)
        expected = request.expected_revision if request else row.hold_revision
        if request and control.revision != expected:
            raise HTTPException(409, detail="Control revision changed; refresh before requesting return.")
        if row.status == "returned":
            return OverrideResponse.model_validate(row)
        if row.status not in {"restored", "return_blocked"} or not row.restored_at:
            raise HTTPException(409, detail="Verified restoration required before return.")
        actor_id = claims.user_id if claims else row.actor_id
        network_id, workspace_id, checkpoint = row.network_id, row.workspace_id, row.checkpoint_sha256
        mode = row.return_mode
        await self.db.commit()
        reasons = []
        observation, qualification, operational = None, None, None
        try:
            await authorize(db=self.db, redis=self.redis, network_id=network_id, workspace_id=workspace_id,
                            actor_id=actor_id, write=True)
        except HTTPException:
            reasons.append("return_actor_unauthorized")
        if mode != "monitor":
            try:
                await self.get_providers()
                reasons_ready, qualification = await readiness(self.providers, checkpoint,
                    production=get_settings().EXECUTION_MODE == "production", require_executor=mode == "autonomous")
                reasons.extend(reasons_ready)
                async with asyncio.timeout(5):
                    observation = Observation.model_validate(await self.providers.observer.observe(network_id, workspace_id))
                from app.modules.autonomy.worker import validate_observation

                operational = await self.repo.operational(network_id)
                reasons.extend(validate_observation(observation, control, qualification,
                    max_age_seconds=operational.max_observation_age_seconds))
            except Exception:  # noqa: BLE001 - missing live compatibility is never replaced by historical inference
                reasons.append("live_return_readiness_failed")
        if claims:
            await self.scope(claims, network_id, write=True)
        else:
            try:
                await authorize(db=self.db, redis=self.redis, network_id=network_id, workspace_id=workspace_id,
                                actor_id=actor_id, write=True)
            except HTTPException:
                reasons.append("return_actor_unauthorized")
        control = await self.repo.get(network_id, lock=True)
        row = await self.repo.override(override_id, lock=True)
        if row.status == "returned":
            await self.db.commit()
            return OverrideResponse.model_validate(row)
        if control.revision != expected:
            reasons.append("control_changed_before_return")
        if control.emergency_stopped:
            reasons.append("emergency_stop_latched")
        if (control.mode != "monitor" or control.workspace_id != workspace_id or control.active_execution_id
                or control.cancellation_status in {"requested", "uncertain"} or await self.repo.unresolved_override(network_id)):
            reasons.append("control_not_available_for_return")
        if control.checkpoint_sha256 != checkpoint:
            reasons.append("model_changed_before_return")
        now = datetime.now(UTC)
        if observation is not None and qualification is not None and operational is not None:
            reasons.extend(validate_observation(observation, control, qualification, now=now,
                max_age_seconds=operational.max_observation_age_seconds))
        if mode == "autonomous" and (
            not row.prior_approval_expires_at or row.prior_approval_expires_at <= now
            or row.prior_approved_by_user_id != actor_id or control.approved_by_user_id != actor_id
            or control.approval_expires_at != row.prior_approval_expires_at
        ):
            reasons.append("prior_approval_expired_or_changed")
        if request:
            row.return_requested_at, row.return_requested_by_user_id, row.return_reason = now, actor_id, request.reason
        row.updated_at = now
        if reasons:
            row.status, row.reasons = "return_blocked", list(dict.fromkeys(reasons))
        else:
            control.mode, control.updated_at = mode, now
            control.revision += 1
            control.claim_token, control.lease_expires_at = None, None
            # STOP fields are intentionally NEVER cleared by return.
            row.status, row.reasons, row.returned_at = "returned", [], now
            await self.repo.invalidate_observing(network_id, "override_mode_return")
            self.repo.record(control, status="control_changed", reasons=["override_mode_return"], actor_id=actor_id)
        if request is not None:
            # Operator-requested returns are audited; worker-driven returns record decisions only.
            await governance.audit(self.db, self.redis, event_type="autonomy.override.return_requested",
                actor_id=actor_id, network_id=network_id, workspace_id=workspace_id, correlation_id=correlation_id,
                resource_type="autonomy_override", resource_id=override_id, metadata={
                    "override_id": str(override_id), "return_mode": mode, "status": row.status,
                    "reasons": list(row.reasons)[:32], "reason": request.reason[:256]})
        await self.db.commit()
        return OverrideResponse.model_validate(row)


class OverrideWorker:
    def __init__(self, *, sessions, redis, providers=None, intent_factory=IntentOverrideService, lease_seconds=30):
        self.sessions, self.redis, self.providers = sessions, redis, providers
        self.intent_factory, self.lease_seconds = intent_factory, lease_seconds

    async def run_one(self):
        async with self.sessions() as db:
            row = await AutonomyRepository(db).claim_override(self.lease_seconds)
        if row is None:
            return False
        try:
            async with asyncio.timeout(self.lease_seconds * .8):
                await self.reconcile(row)
        except Exception:  # noqa: BLE001 - keep the claim durable; retry after lease expiry
            logger.warning("override_reconciliation_retry", override_id=str(row.override_id))
        return True

    async def reconcile(self, claimed):
        if claimed.status == "restored":
            async with self.sessions() as db:
                await OverrideService(db, self.redis, providers=self.providers, sessions=self.sessions).return_mode(
                    override_id=claimed.override_id)
            return
        authority_failed = False
        try:
            async with self.sessions() as db:
                await authorize(db=db, redis=self.redis, network_id=claimed.network_id, workspace_id=claimed.workspace_id,
                                actor_id=claimed.actor_id, write=True)
        except Exception:  # noqa: BLE001 - server compensation survives revoked or unavailable actor authority
            authority_failed = True
        async with self.sessions() as db:
            repo = AutonomyRepository(db)
            control = await repo.get(claimed.network_id, lock=True)
            row = await repo.owned_override(claimed.override_id, claimed.claim_token)
            if row is None:
                return
            now = datetime.now(UTC)
            if row.status == "holding" and (authority_failed or control.emergency_stopped or now >= row.expires_at):
                row.status = "restoring"
                row.reasons = ["actor_authority_revoked" if authority_failed else
                               "emergency_stop_latched" if control.emergency_stopped else "override_expired"]
                row.cancellation_id, row.cancellation_requested_at = row.execution_id, now
            if row.status != "restoring":
                row.claim_token, row.lease_expires_at = None, None
                row.next_check_at = min(row.expires_at, now + timedelta(seconds=2))
                await db.commit()
                return
            row.restoration_attempts += 1
            row.updated_at = now
            reference = dict(row.recovery_reference)
            await db.commit()
        try:
            async with self.sessions() as db:
                result = await self.intent_factory(db, self.redis).restore_override(reference)
        except Exception:  # noqa: BLE001 - retain exclusion, diagnostic and retry even for a cancelled unknown Intent
            result = {"status": "uncertain", "safe_to_release": False, "reasons": ["intent_restoration_unavailable"]}
        async with self.sessions() as db:
            repo = AutonomyRepository(db)
            row = await repo.owned_override(claimed.override_id, claimed.claim_token)
            if row is None or row.status != "restoring":
                return
            row.verification, row.updated_at = result, datetime.now(UTC)
            safe = (result.get("execution_id") == str(row.execution_id) and result.get("status") == "cancelled"
                    and result.get("safe_to_release") is True and bool(result.get("evidence")))
            if safe:
                row.status, row.restored_at, row.reasons = "restored", datetime.now(UTC), []
            else:
                row.reasons = list(dict.fromkeys([*row.reasons, *result.get("reasons", []), "restoration_unverified"]))
            row.claim_token, row.lease_expires_at = None, None
            row.next_check_at = datetime.now(UTC) + timedelta(seconds=2)
            await db.commit()
        if safe:
            async with self.sessions() as db:
                await OverrideService(db, self.redis, providers=self.providers, sessions=self.sessions).return_mode(
                    override_id=claimed.override_id)

    async def run(self):
        while True:
            try:
                async with worker_iteration("overrides"):
                    await self.run_one()
            except Exception:  # noqa: BLE001 - independent of full autonomy/provider failures
                logger.warning("override_worker_retry")
            await asyncio.sleep(1)
