"""Immutable requested configuration; frozen training parameters are never modified."""

from datetime import UTC, datetime

from fastapi import HTTPException

from app.core.canonical import canonical_sha256
from app.modules.autonomy.models import ConfigurationRevision
from app.modules.autonomy.schemas import (
    ConfigurationResponse,
    ConfigurationRevisionResponse,
    OperationalSettings,
    TrainingSettings,
)
from app.modules.autonomy.service import AutonomyService


class ConfigurationService(AutonomyService):
    async def get(self, *, claims, network_id):
        network, _ = await self.scope(claims, network_id)
        control = await self.repo.get(network_id)
        rows = await self.repo.configurations(network_id)
        if any(row.workspace_id != network.workspace_id for row in rows) or (
            control and control.workspace_id != network.workspace_id
        ):
            raise HTTPException(409, detail="Network ownership changed; reconciliation required.")
        training = TrainingSettings.model_validate(rows[0].training) if rows else TrainingSettings()
        return ConfigurationResponse(network_id=network_id, workspace_id=network.workspace_id,
            revision=rows[0].revision if rows else 0, control_revision=control.revision if control else 0,
            operational=OperationalSettings.model_validate(rows[0].operational) if rows else OperationalSettings(),
            requested_training=training, training_status="retraining_required" if training.reward_weights else "not_requested",
            history=[ConfigurationRevisionResponse.model_validate(row) for row in rows])

    async def put(self, *, claims, request):
        network, _ = await self.scope(claims, request.network_id, write=True)
        control = await self.repo.ensure(request.network_id, network.workspace_id)
        rows = await self.repo.configurations(request.network_id, 1)
        revision = rows[0].revision if rows else 0
        if control.workspace_id != network.workspace_id or revision != request.expected_revision:
            await self.db.rollback()
            raise HTTPException(409, detail={"code": "CONFIGURATION_REVISION_CONFLICT", "message": "Refresh configuration before editing."})
        operational, training = request.operational.model_dump(mode="json"), request.training.model_dump(mode="json")
        content_hash = canonical_sha256({"operational": operational, "training": training})
        self.db.add(ConfigurationRevision(network_id=request.network_id, workspace_id=network.workspace_id,
            revision=revision + 1, actor_id=claims.user_id, reason=request.reason,
            operational=operational, training=training, content_sha256=content_hash))
        control.revision += 1
        control.claim_token, control.lease_expires_at = None, None
        control.next_cycle_at, control.updated_at = datetime.now(UTC), datetime.now(UTC)
        await self.repo.invalidate_observing(control.network_id, "configuration_changed_before_acceptance")
        self.repo.record(control, status="control_changed", reasons=["configuration_revision_changed"], actor_id=claims.user_id)
        await self.db.commit()
        return await self.get(claims=claims, network_id=request.network_id)
