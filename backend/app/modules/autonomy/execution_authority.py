"""Receiver-side owning authority checks; recovery never uses requester permissions."""

from datetime import UTC, datetime

from app.modules.autonomy.provider_state import ProviderStateRepository
from app.modules.autonomy.repository import AutonomyRepository
from app.modules.autonomy.safety import SafetyState
from app.modules.autonomy.schemas import Observation, Proposal, SafetyAssessment, contract_digest
from app.modules.autonomy.service import authorize


class ExecutionAuthority:
    def __init__(self, redis, safety_provider, *, execution_mode):
        self.redis, self.safety = redis, safety_provider
        self.execution_mode = execution_mode
        self.runtime_guard = None

    async def check(self, db, authorization, *, accepted=False):
        self.safety.installation.assert_reviewed_execution()
        if self.runtime_guard is not None:
            await self.runtime_guard(authorization)
        if self.execution_mode != "emulation":
            raise ValueError("production_autonomous_driver_unavailable")
        auth = authorization
        repo = AutonomyRepository(db)
        # Control first in lock order, matching AutonomyWorker acceptance/STOP.
        control = await repo.get(auth.network_id, lock=True)
        await authorize(db=db, redis=self.redis, network_id=auth.network_id, workspace_id=auth.workspace_id,
                        actor_id=auth.actor_id, write=True)
        now = datetime.now(UTC)
        if (control is None or control.workspace_id != auth.workspace_id or control.mode != "autonomous"
                or control.emergency_stopped or control.revision != auth.control_revision
                or control.approved_by_user_id != auth.actor_id or control.checkpoint_sha256 != auth.checkpoint_sha256
                or control.approval_expires_at != auth.approval_expires_at or now >= auth.approval_expires_at
                or now.timestamp() >= auth.certificate_expires_at_unix_seconds
                or await repo.unresolved_override(auth.network_id)):
            raise ValueError("receiver_current_authority_denied")
        if accepted:
            if (control.active_execution_id != auth.execution_id or control.active_intent_id != auth.intent_id
                    or control.active_decision_id != auth.decision_id):
                raise ValueError("receiver_active_identity_mismatch")
        elif (control.claim_token != auth.claim_token or control.lease_expires_at is None
              or control.lease_expires_at <= now or control.active_execution_id is not None):
            raise ValueError("acceptance_claim_expired")
        safety = SafetyAssessment.model_validate_json(auth.safety_evidence_json)
        if not safety.binding or not safety.selected_action or not safety.certificate:
            raise ValueError("receiver_safety_binding_missing")
        data = self.safety.installation.data
        if (safety.binding.policy != data.policy or safety.binding.calibration != data.calibration
                or safety.binding.calibration_sha256 != contract_digest(data.calibration)
                or safety.binding.workspace_id != auth.workspace_id or data.workspace_id != auth.workspace_id
                or data.network_id != auth.network_id or auth.checkpoint_sha256 not in data.checkpoints):
            raise ValueError("receiver_calibration_not_installed")
        from app.modules.autonomy.execution_models import AutonomousObservation

        frame = await db.get(AutonomousObservation, safety.binding.observation_sha256)
        history = await ProviderStateRepository(db).history(auth.network_id)
        if (frame is None or history is None or history.installation_sha256 != self.safety.installation.sha256
                or history.workspace_id != auth.workspace_id
                or frame.safety_observation != safety.binding.observation.model_dump(mode="json")):
            raise ValueError("receiver_measured_history_missing")
        observation = Observation.model_validate(frame.observation)
        # Proposal is retained in the owning decision before committed dispatch.
        decision = await repo.decision(auth.decision_id)
        if not decision.proposal:
            raise ValueError("receiver_proposal_missing")
        proposal = Proposal.model_validate(decision.proposal)
        if contract_digest(proposal) != safety.binding.proposal_sha256:
            raise ValueError("receiver_proposal_digest_mismatch")
        if (decision.network_id != auth.network_id or decision.workspace_id != auth.workspace_id
                or proposal.checkpoint_sha256 != auth.checkpoint_sha256
                or contract_digest(observation) != safety.binding.observation_sha256):
            raise ValueError("receiver_decision_binding_mismatch")
        state = SafetyState.model_validate({**history.state,
            "snapshot_id": safety.binding.observation.snapshot_id,
            "observed_at_unix_seconds": safety.binding.observation.observed_at_unix_seconds})
        # Before first device dispatch history must be exactly the evaluated history.
        # Later checkpoints use the persisted binding while ownership excludes new actions.
        if not accepted and state != safety.binding.state:
            raise ValueError("receiver_history_changed")
        reevaluated = self.safety.evaluate(observation, proposal, safety.binding.observation,
            safety.binding.state, now=safety.binding.evaluated_at_unix_seconds)
        if reevaluated != safety or contract_digest(safety) != auth.safety_sha256:
            raise ValueError("receiver_calibrated_certificate_mismatch")
        from app.modules.autonomy.worker import operational_safety_reasons

        settings = await repo.operational(auth.network_id)
        if operational_safety_reasons(settings, safety):
            raise ValueError("receiver_operational_policy_denied")
        # Authority/profile reads may have waited; never dispatch on the old clock.
        final_now = datetime.now(UTC)
        if final_now >= auth.approval_expires_at or final_now.timestamp() >= auth.certificate_expires_at_unix_seconds:
            raise ValueError("receiver_deadline_elapsed_during_validation")
