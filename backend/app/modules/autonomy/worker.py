"""Reusable bounded observe/validate/infer/safety/approve/execute/verify cycle."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.runtime_health import worker_iteration
from app.modules.autonomy.providers import installed_providers
from app.modules.autonomy.repository import AutonomyRepository
from app.modules.autonomy.safety import SafetyShield
from app.modules.autonomy.schemas import (
    ExecutionAuthorization,
    ExecutionReference,
    Observation,
    Proposal,
    SafetyAssessment,
    Verification,
    canonical_json,
    contract_digest,
)
from app.modules.autonomy.service import approval_reasons, authorize, readiness

logger = get_logger(__name__)


def validate_observation(observation, control, qualification=None, *, now=None, max_age_seconds=30):
    now = now or datetime.now(UTC)
    reasons = list(observation.reasons)
    if observation.network_id != control.network_id or observation.workspace_id != control.workspace_id:
        reasons.append("observation_scope_mismatch")
    if qualification is not None and (not observation.compatible or observation.contract != qualification.observation_contract):
        reasons.append("observation_contract_incompatible")
    age = (now - observation.observed_at).total_seconds() if observation.observed_at else None
    if not observation.fresh or age is None or not 0 <= age <= min(30, max_age_seconds):
        reasons.append("observation_stale_or_missing")
    if not 0 <= (now - observation.collected_at).total_seconds() <= min(30, max_age_seconds):
        reasons.append("observation_delayed")
    if not observation.evidence:
        reasons.append("observation_evidence_missing")
    return list(dict.fromkeys(reasons))


def validate_safety(safety, observation, proposal, *, now=None):
    """Bind the complete shield output, then recheck its exclusive dispatch horizon."""
    now = (now or datetime.now(UTC)).timestamp()
    binding, action, certificate = safety.binding, safety.selected_action, safety.certificate
    if not safety.admissible:
        return safety.reasons or ["safety_refused"]
    if not binding or not action or not certificate or not safety.evidence:
        return ["safety_certificate_missing"]
    if (binding.workspace_id != observation.workspace_id
            or binding.observation_sha256 != contract_digest(observation)
            or binding.proposal_sha256 != contract_digest(proposal)
            or binding.calibration_sha256 != contract_digest(binding.calibration)
            or binding.selected_action_sha256 != contract_digest(action)
            or action.network_id != str(observation.network_id)
            or binding.observation.network_id != str(observation.network_id)
            or observation.observed_at is None
            or binding.observation.observed_at_unix_seconds != observation.observed_at.timestamp()
            or safety.action_id != action.action_id or safety.model_version != certificate.model):
        return ["safety_binding_mismatch"]
    # Re-evaluate the selected candidate from retained validated inputs. This checks
    # arithmetic/route binding, not provider trust or physical calibration installation.
    result = SafetyShield(binding.policy, binding.calibration).evaluate(
        binding.observation, action, state=binding.state, now=binding.evaluated_at_unix_seconds)
    if (result["decision"] != "accept" or result["certificate"] != certificate.model_dump(mode="json")
            or result["selected_action"] != action.model_dump(mode="json")):
        return ["safety_certificate_mismatch"]
    if not binding.evaluated_at_unix_seconds <= now < certificate.expires_at_unix_seconds:
        return ["safety_certificate_expired"]
    return []


def operational_safety_reasons(settings, safety, *, now=None):
    """Additional gates only: the original calibrated certificate stays mandatory."""
    now = (now or datetime.now(UTC)).timestamp()
    binding = safety.binding
    if not binding:
        return ["operational_safety_state_missing"]
    state, policy = binding.state, binding.policy
    reasons = []
    if now - binding.observation.observed_at_unix_seconds > min(settings.max_observation_age_seconds, policy.max_observation_age_seconds):
        reasons.append("configured_observation_age_exceeded")
    if now - state.route_since_unix_seconds < max(settings.min_route_hold_seconds, policy.min_dwell_seconds):
        reasons.append("configured_route_hold")
    if state.history_complete_since_unix_seconds > now - 60:
        reasons.append("configured_change_history_incomplete")
    if sum(now - 60 < stamp <= now for stamp in state.recent_dispatch_at_unix_seconds) >= settings.max_changes_per_minute:
        reasons.append("configured_change_rate_exceeded")
    return reasons


class AutonomyWorker:
    def __init__(self, *, sessions, redis, providers=None, interval_seconds=10, lease_seconds=30):
        if not 1 <= interval_seconds <= 3600 or not 10 <= lease_seconds <= 300:
            raise ValueError("Invalid worker bounds")
        self.sessions, self.redis = sessions, redis
        self.providers = providers or installed_providers(sessions, redis)
        self.interval_seconds, self.lease_seconds = interval_seconds, lease_seconds

    async def run_one(self):
        async with self.sessions() as db:
            claimed = await AutonomyRepository(db).claim(lease_seconds=self.lease_seconds, interval_seconds=self.interval_seconds)
        if claimed is None:
            return False
        control, decision = claimed
        try:
            async with asyncio.timeout(self.lease_seconds * .8):
                await self.cycle(control, decision)
        except TimeoutError:
            await self.finish(control, decision, status="blocked", reasons=["cycle_deadline_exceeded"])
        except HTTPException:
            await self.finish(control, decision, status="blocked", reasons=["approval_actor_unauthorized"])
        except Exception:  # noqa: BLE001 - isolate failure and retain durable diagnostics, not exception secrets
            await self.finish(control, decision, status="blocked", reasons=["cycle_provider_or_authority_failed"])
        return True

    async def cycle(self, control, decision):
        if control.active_execution_id:
            await self.reconcile(control, decision)
            return
        async with self.sessions() as db:
            operational = await AutonomyRepository(db).operational(control.network_id)
            if await AutonomyRepository(db).unresolved_override(control.network_id):
                await self.finish(control, decision, status="blocked", reasons=["timed_override_unresolved"])
                return
            await authorize(db=db, redis=self.redis, network_id=control.network_id, workspace_id=control.workspace_id,
                            actor_id=(control.stopped_by_user_id if control.emergency_stopped else control.approved_by_user_id),
                            write=control.mode != "monitor" or bool(control.active_execution_id))
        reasons = approval_reasons(control)
        if reasons:
            await self.finish(control, decision, status="blocked", reasons=reasons)
            return
        observation = Observation.model_validate(await self.providers.observer.observe(control.network_id, control.workspace_id))
        # Never retain foreign-scope provider evidence in a tenant's decision history.
        if observation.network_id != control.network_id or observation.workspace_id != control.workspace_id:
            await self.finish(control, decision, status="blocked", reasons=["observation_scope_mismatch"])
            return
        async with self.sessions() as db:
            repo = AutonomyRepository(db)
            current = await repo.owned(control.network_id, control.claim_token)
            if current is None:
                return
            row = await repo.decision(decision.decision_id)
            self.update_decision(row, status="observing", reasons=observation.reasons, observation=observation)
            await db.commit()
        if control.mode == "monitor":
            await self.finish(control, decision, status="observed", reasons=validate_observation(observation, control,
                              max_age_seconds=operational.max_observation_age_seconds),
                              observation=observation)
            return
        reasons, qualification = await readiness(self.providers, control.checkpoint_sha256,
                                               production=get_settings().EXECUTION_MODE == "production",
                                               require_executor=control.mode == "autonomous")
        reasons.extend(validate_observation(observation, control, qualification, max_age_seconds=operational.max_observation_age_seconds))
        if reasons:
            await self.finish(control, decision, status="blocked", reasons=reasons, observation=observation)
            return
        proposal = Proposal.model_validate(await self.providers.model.infer(observation, qualification))
        if proposal.checkpoint_sha256 != control.checkpoint_sha256 or proposal.observation_contract != observation.contract:
            await self.finish(control, decision, status="blocked", reasons=["inference_identity_mismatch"], observation=observation)
            return
        safety = SafetyAssessment.model_validate(await self.providers.safety.assess(observation, proposal))
        reasons = validate_safety(safety, observation, proposal)
        if not reasons:
            reasons.extend(operational_safety_reasons(operational, safety))
        if reasons:
            await self.finish(control, decision, status="blocked", reasons=reasons,
                              observation=observation, proposal=proposal, safety=safety)
            return
        if control.mode == "recommend":
            await self.finish(control, decision, status="recommended", reasons=["recommendation_only"],
                              observation=observation, proposal=proposal, safety=safety)
            return
        # Qualification/provider I/O finishes before the short transactional acceptance lock.
        manifest_sha256 = qualification.manifest_sha256
        reasons, qualification = await readiness(self.providers, control.checkpoint_sha256,
                                               production=get_settings().EXECUTION_MODE == "production")
        if qualification.manifest_sha256 != manifest_sha256:
            reasons.append("qualification_changed_before_acceptance")
        async with self.sessions() as db:
            repo = AutonomyRepository(db)
            current = await repo.owned(control.network_id, control.claim_token)
            if current is None:
                return
            await authorize(db=db, redis=self.redis, network_id=current.network_id, workspace_id=current.workspace_id,
                            actor_id=current.approved_by_user_id, write=True)
            # Authorization DB reads can themselves outlast the lease under contention.
            current = await repo.owned(control.network_id, control.claim_token)
            if current is None:
                return
            reasons.extend(approval_reasons(current))
            if await repo.unresolved_override(current.network_id):
                reasons.append("timed_override_unresolved")
            operational = await repo.operational(current.network_id)
            reasons.extend(validate_observation(observation, current, qualification, max_age_seconds=operational.max_observation_age_seconds))
            reasons.extend(validate_safety(safety, observation, proposal))
            reasons.extend(operational_safety_reasons(operational, safety))
            if (current.last_accepted_observed_at and observation.observed_at
                    and current.last_accepted_observed_at >= observation.observed_at):
                reasons.append("observation_replayed")
            if current.mode != "autonomous" or current.revision != control.revision:
                reasons.append("control_changed_before_acceptance")
            if reasons:
                await db.rollback()
                await self.finish(control, decision, status="blocked", reasons=reasons,
                                  observation=observation, proposal=proposal, safety=safety)
                return
            authorization = ExecutionAuthorization(decision_id=decision.decision_id, execution_id=uuid.uuid4(),
                intent_id=uuid.uuid4(), network_id=current.network_id, workspace_id=current.workspace_id,
                actor_id=current.approved_by_user_id, checkpoint_sha256=current.checkpoint_sha256,
                approval_expires_at=current.approval_expires_at, control_revision=current.revision,
                claim_token=current.claim_token, safety_evidence_json=canonical_json(safety),
                selected_action_json=canonical_json(safety.selected_action),
                safety_sha256=contract_digest(safety), selected_action_sha256=contract_digest(safety.selected_action),
                certificate_expires_at_unix_seconds=safety.certificate.expires_at_unix_seconds)
            # No installed implementation exists. An adapter must enlist in this same
            # transaction, not wait on a controller or commit internally. Stop serializes here.
            await self.providers.executor.accept(db, authorization)
            # Staging may wait on DB locks. Roll back enlisted work if its authority
            # expired during the callback; the receiver must also fence actual dispatch.
            await authorize(db=db, redis=self.redis, network_id=current.network_id,
                            workspace_id=current.workspace_id, actor_id=current.approved_by_user_id, write=True)
            current = await repo.owned(control.network_id, control.claim_token)
            if current is None:
                await db.rollback()
                return
            reasons = approval_reasons(current)
            reasons.extend(validate_observation(observation, current, qualification, max_age_seconds=operational.max_observation_age_seconds))
            reasons.extend(validate_safety(safety, observation, proposal))
            reasons.extend(operational_safety_reasons(operational, safety))
            if contract_digest(safety) != authorization.safety_sha256:
                reasons.append("safety_changed_during_acceptance")
            if current.revision != authorization.control_revision or current.mode != "autonomous":
                reasons.append("control_changed_before_acceptance")
            if reasons:
                await db.rollback()
                await self.finish(control, decision, status="blocked", reasons=reasons,
                                  observation=observation, proposal=proposal, safety=safety)
                return
            current.active_execution_id, current.active_intent_id = authorization.execution_id, authorization.intent_id
            current.active_decision_id = decision.decision_id
            row = await repo.decision(decision.decision_id)
            self.update_decision(row, status="accepted", reasons=["durable_acceptance_not_verification"],
                                 observation=observation, proposal=proposal, safety=safety)
            row.execution_id = authorization.execution_id
            row.authorization = authorization.model_dump(mode="json")
            row.evidence = list(dict.fromkeys([*row.evidence, *qualification.evidence,
                                              f"qualification_manifest:{qualification.manifest_sha256}"]))[:100]
            current.last_observation = observation.model_dump(mode="json")
            current.last_accepted_observed_at = observation.observed_at
            await db.commit()
        # Verification is always outside acceptance transaction and cannot fabricate completion.
        control.active_execution_id, control.active_intent_id = authorization.execution_id, authorization.intent_id
        control.active_decision_id = decision.decision_id
        await self.reconcile(control, decision)

    async def reconcile(self, control, decision):
        async with self.sessions() as db:
            current = await AutonomyRepository(db).owned(control.network_id, control.claim_token)
            if current is None or not current.active_execution_id:
                return
            reference = ExecutionReference(network_id=current.network_id, workspace_id=current.workspace_id,
                intent_id=current.active_intent_id, execution_id=current.active_execution_id,
                decision_id=current.active_decision_id, control_revision=current.revision, claim_token=current.claim_token)
        try:
            result = Verification.model_validate(await self.providers.executor.verify(reference))
        except Exception:  # noqa: BLE001 - recovery must still run if readback is unavailable
            result = Verification(execution_id=reference.execution_id, status="uncertain", reasons=["execution_verification_failed"])
        if result.execution_id != reference.execution_id:
            raise ValueError("verification identity mismatch")
        authority_reasons = []
        try:
            async with self.sessions() as db:
                await authorize(db=db, redis=self.redis, network_id=reference.network_id, workspace_id=reference.workspace_id,
                                actor_id=control.approved_by_user_id, write=True)
        except Exception:  # noqa: BLE001 - failed authority requires recovery, never stale-actor impersonation
            authority_reasons = ["approval_actor_unauthorized"]
        async with self.sessions() as db:
            repo = AutonomyRepository(db)
            current = await repo.owned(control.network_id, control.claim_token)
            if current is None or current.active_execution_id != reference.execution_id:
                return
            cancel_required = bool(authority_reasons) or current.emergency_stopped or current.mode != "autonomous" or (
                not current.approval_expires_at or current.approval_expires_at <= datetime.now(UTC))
            if cancel_required:
                current.cancellation_status = "requested"
                await db.commit()
        if cancel_required and not (result.status == "cancelled" and result.safe_to_release and result.evidence):
            try:
                result = Verification.model_validate(await self.providers.recovery.cancel(reference))
            except Exception:  # noqa: BLE001
                result = Verification(execution_id=reference.execution_id, status="uncertain",
                                      reasons=["autonomous_recovery_failed", "operator_recovery_required"])
            if result.execution_id != reference.execution_id:
                raise ValueError("recovery identity mismatch")
        async with self.sessions() as db:
            repo = AutonomyRepository(db)
            current = await repo.owned(control.network_id, control.claim_token)
            if current is None or current.active_execution_id != result.execution_id:
                return
            # A stop/expiry observed after I/O cannot turn an old completion into success.
            cancel_required = cancel_required or current.emergency_stopped or (current.mode == "autonomous" and
                (not current.approval_expires_at or current.approval_expires_at <= datetime.now(UTC)))
            released = (result.safe_to_release and bool(result.evidence)
                        and result.status in ({"cancelled"} if cancel_required else {"verified", "cancelled", "failed"}))
            row = await repo.decision(decision.decision_id)
            row.execution_id, row.verification = result.execution_id, result.model_dump(mode="json")
            row.status = result.status if released else "uncertain"
            row.reasons = list(dict.fromkeys([*authority_reasons, *result.reasons, *([] if released else ["execution_unresolved"])]))
            row.evidence, row.updated_at = result.evidence, datetime.now(UTC)
            if released:
                current.active_execution_id, current.active_intent_id, current.active_decision_id = None, None, None
                current.cancellation_status = "verified" if result.status == "cancelled" else "none"
            else:
                current.cancellation_status = "requested" if cancel_required and result.status == "pending" else "uncertain"
            current.claim_token, current.lease_expires_at = None, None
            current.updated_at = datetime.now(UTC)
            await db.commit()

    @staticmethod
    def update_decision(row, *, status, reasons, observation=None, proposal=None, safety=None):
        row.status, row.reasons, row.updated_at = status, list(dict.fromkeys(reasons)), datetime.now(UTC)
        for name, value in (("observation", observation), ("proposal", proposal), ("safety", safety)):
            if value is not None:
                setattr(row, name, value.model_dump(mode="json"))
        row.evidence = list(dict.fromkeys([
            *(row.evidence or []),
            *(item for value in (observation, proposal, safety) if value for item in value.evidence),
        ]))[:100]

    async def finish(self, control, decision, *, status, reasons, observation=None, proposal=None, safety=None):
        async with self.sessions() as db:
            repo = AutonomyRepository(db)
            current = await repo.owned(control.network_id, control.claim_token)
            if current is None:
                return
            row = await repo.decision(decision.decision_id)
            if current.active_execution_id:
                status = "uncertain"
                reasons = [*reasons, "execution_unresolved"]
                current.cancellation_status = "uncertain"
                row.execution_id = current.active_execution_id
            self.update_decision(row, status=status, reasons=reasons, observation=observation, proposal=proposal, safety=safety)
            if observation:
                current.last_observation = observation.model_dump(mode="json")
            current.claim_token, current.lease_expires_at = None, None
            current.updated_at = datetime.now(UTC)
            await db.commit()

    async def run(self):
        from app.modules.autonomy.overrides import OverrideWorker

        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(OverrideWorker(sessions=self.sessions, redis=self.redis, providers=self.providers).run())
            tasks.create_task(self._cycles())

    async def _cycles(self):
        while True:
            try:
                async with worker_iteration("cycles"):
                    await self.run_one()
            except Exception:  # noqa: BLE001 - DB outages must not spin or kill the independent worker
                logger.warning("autonomy_cycle_failed")
            await asyncio.sleep(1)
