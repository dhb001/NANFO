"""Owning public boundary for measured frames; never derives missing measurements."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.modules.autonomy.execution_models import (
    AutonomousExecution,
    AutonomousObservation,
    AutonomousProviderState,
)
from app.modules.autonomy.safety import SafetyObservation, SafetyState
from app.modules.autonomy.schemas import Observation, contract_digest


class ProviderStateRepository:
    def __init__(self, db):
        self.db = db

    async def record_observation(self, observation: Observation, safety_observation: SafetyObservation):
        observation = Observation.model_validate(observation)
        frame = SafetyObservation.model_validate(safety_observation)
        if (frame.network_id != str(observation.network_id) or observation.observed_at is None
                or frame.observed_at_unix_seconds != observation.observed_at.timestamp()
                or not observation.evidence or not observation.compatible or not observation.fresh):
            raise ValueError("measured_frame_binding_mismatch")
        digest = contract_digest(observation)
        from app.modules.telemetry.pins import EvidenceOwnerScope, TelemetryEvidenceService
        from app.modules.telemetry.references import evidence_item

        pins = TelemetryEvidenceService(self.db, scope=EvidenceOwnerScope(
            owner="autonomy", workspace_id=observation.workspace_id))
        values = dict(observation_sha256=digest, network_id=observation.network_id,
                      workspace_id=observation.workspace_id, observation=observation.model_dump(mode="json"),
                      safety_observation=frame.model_dump(mode="json"))
        references = evidence_item(identity=f"autonomous_observations:{digest}", network_id=observation.network_id,
            fields={key: values[key] for key in ("observation", "safety_observation")})
        for reference in sorted(references.references, key=lambda ref: (ref.record_id, ref.reference_id)):
            await pins.pin(reference)
        await self.db.execute(insert(AutonomousObservation).values(**values).on_conflict_do_nothing())
        row = await self.db.get(AutonomousObservation, digest)
        if row.safety_observation != values["safety_observation"]:
            raise ValueError("measured_frame_is_immutable")
        return digest

    async def seed_history(self, *, installation, state: SafetyState, evidence: list[str]):
        """Operator-only attested baseline, insert-once; cannot erase dispatch history."""
        state = SafetyState.model_validate(state)
        data = installation.data
        if (state.network_id != data.calibration.network_id or state.run_id != data.calibration.run_id
                or not evidence or len(evidence) > 100):
            raise ValueError("invalid_attested_baseline")
        row = AutonomousProviderState(network_id=data.network_id, workspace_id=data.workspace_id,
            installation_sha256=installation.sha256, state=state.model_dump(mode="json"), evidence=evidence)
        self.db.add(row)
        await self.db.flush()

    async def history(self, network_id, *, lock=False):
        query = select(AutonomousProviderState).where(AutonomousProviderState.network_id == network_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(query)

    async def inputs(self, observation, installation):
        frame = await self.db.get(AutonomousObservation, contract_digest(observation))
        history = await self.history(observation.network_id)
        busy = await self.db.scalar(select(AutonomousExecution.execution_id).where(
            AutonomousExecution.network_id == observation.network_id, AutonomousExecution.released.is_(False)))
        if (frame is None or history is None or busy or history.workspace_id != observation.workspace_id
                or history.installation_sha256 != installation.sha256
                or frame.observation != observation.model_dump(mode="json")):
            raise ValueError("measured_frame_or_history_unavailable")
        obs = SafetyObservation.model_validate(frame.safety_observation)
        state = SafetyState.model_validate({**history.state, "snapshot_id": obs.snapshot_id,
                                           "observed_at_unix_seconds": obs.observed_at_unix_seconds})
        return obs, state
