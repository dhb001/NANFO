"""Inventory deletion policy. Foreign state is read only through owning services."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.modules.network.asset_mapping import normalize_asset_device_mapping
from app.modules.network.models import (
    CampusBuildingRecord,
    CampusModelAssetRecord,
    Device,
    DeviceGroup,
    DeviceGroupMember,
)
from app.modules.network.spatial_models import SpatialSceneRecord


def _conflict(resource):
    raise HTTPException(status_code=409, detail={
        "code": "INVENTORY_DEPENDENCIES_ACTIVE",
        "message": f"Remove or resolve active {resource} before deleting inventory.",
    })


def _verified_intent_restoration(detail, *, intent_id, network) -> bool:
    """Use only current owner detail and the owner's existing evidence validators.

    A successful applied policy is not restoration. A rollback belongs to the exact
    execution projected by Intent after its worker matched the fenced receipt.
    Separate restore executions prove only their own plan, never unrelated intents.
    """
    from app.modules.intent.lab import LabPlan, digest, verified_completion, verified_rollback

    if not isinstance(detail, dict) or any(detail.get(key) != str(value) for key, value in (
        ("intent_id", intent_id), ("network_id", network.network_id), ("workspace_id", network.workspace_id),
    )):
        return False
    proof = detail.get("execution_provenance")
    if (not isinstance(proof, dict) or proof.get("executor") != "manual_lab_v1"
            or proof.get("blocks_lab") is not False or proof.get("uncertain") is not False
            or proof.get("status") != detail.get("status")):
        return False
    try:
        for key in ("execution_id", "run_id"):
            uuid.UUID(proof[key])
        for key in ("plan_hash", "binding_digest"):
            value = proof[key]
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                return False
        approved = datetime.fromisoformat(proof["approved_at"])
        completed = datetime.fromisoformat(proof["completed_at"])
        if approved.tzinfo is None or completed.tzinfo is None or not approved <= completed <= datetime.now(UTC):
            return False
        plan = LabPlan.model_validate(proof["approved_plan"])
        if digest(plan.model_dump(mode="json")) != proof["plan_hash"]:
            return False
    except (KeyError, TypeError, ValueError, AttributeError, ValidationError):
        return False
    if detail["status"] == "execution_failed" and proof.get("phase") in {"failed", "cancelled"}:
        return verified_rollback(proof.get("rollback"))
    if detail["status"] == "execution_completed" and proof.get("phase") == "completed" and plan.operation == "restore":
        verification = proof.get("verification")
        if not isinstance(verification, dict) or not verified_completion(verification):
            return False
        probe = verification["probe"]
        return (probe.get("source_host") == plan.source_host
                and probe.get("destination_host") == plan.destination_host)
    return False


class InventoryDependencyRepository:
    """Only Network-owned tables. Historical scene revisions are never blockers."""

    def __init__(self, db):
        self.db = db

    async def assert_safe(self, network_id, device_id=None):
        if device_id is None:
            for model, label in ((Device, "devices"), (CampusBuildingRecord, "campus buildings"),
                                 (CampusModelAssetRecord, "campus model assets"), (DeviceGroup, "device groups")):
                if await self.db.scalar(select(model.network_id).where(
                    model.network_id == network_id, model.deleted_at.is_(None),
                ).limit(1)):
                    _conflict(label)
        else:
            membership = select(DeviceGroupMember.device_id).join(DeviceGroup).where(
                DeviceGroup.network_id == network_id, DeviceGroup.deleted_at.is_(None),
                DeviceGroupMember.device_id == device_id, DeviceGroupMember.deleted_at.is_(None),
            ).limit(1)
            if await self.db.scalar(membership):
                _conflict("device group memberships")
            mapping = select(CampusModelAssetRecord.network_id).where(
                CampusModelAssetRecord.network_id == network_id,
                CampusModelAssetRecord.deleted_at.is_(None),
                CampusModelAssetRecord.mapping_by_device_id.has_key(str(device_id)),  # noqa: W601
            ).limit(1)
            if await self.db.scalar(mapping):
                _conflict("campus model mappings")
            await self._assert_legacy_asset_mappings_safe(network_id, device_id)
        scene = await self.db.scalar(select(SpatialSceneRecord.scene).where(
            SpatialSceneRecord.network_id == network_id,
        ))
        objects = (scene or {}).get("objects", [])
        if (device_id is None and objects) or any(obj.get("device_id") == str(device_id) for obj in objects):
            _conflict("spatial scene objects")

    async def _assert_legacy_asset_mappings_safe(self, network_id, device_id):
        # Older records preserved UUID spelling. Inspect every active owner row in
        # bounded keyset pages; never cast untrusted JSON keys in SQL or rewrite history.
        after = None
        while True:
            query = select(CampusModelAssetRecord.campus_model_asset_id, CampusModelAssetRecord.mapping_by_device_id).where(
                CampusModelAssetRecord.network_id == network_id, CampusModelAssetRecord.deleted_at.is_(None),
            )
            if after is not None:
                query = query.where(CampusModelAssetRecord.campus_model_asset_id > after)
            rows = (await self.db.execute(query.order_by(CampusModelAssetRecord.campus_model_asset_id).limit(200))).all()
            for asset_id, mapping in rows:
                try:
                    canonical = normalize_asset_device_mapping(mapping)
                except ValueError:
                    _conflict("invalid or ambiguous campus model mappings")
                if str(device_id) in canonical:
                    _conflict("campus model mappings")
            if len(rows) < 200:
                return
            after = rows[-1][0]


class InventoryDeletionService:
    def __init__(self, db, redis):
        self.db, self.redis = db, redis
        self.repository = InventoryDependencyRepository(db)

    async def assert_safe(self, *, network, actor_id, device_id=None):
        await self.repository.assert_safe(network.network_id, device_id)
        await self._assert_workflows_safe(network, actor_id)

    async def _assert_workflows_safe(self, network, actor_id):
        # Local imports avoid the owning services' existing NetworkService imports.
        from app.modules.autonomy.service import AutonomyService
        from app.modules.intent.history import IntentHistoryService
        from app.modules.simulation.history import SimulationHistoryService

        for service, terminal, label in (
            (SimulationHistoryService(self.db, self.redis), {"completed", "cancelled", "failed"}, "simulations"),
            (IntentHistoryService(self.db, self.redis),
             {"rejected", "cancelled", "compensated", "execution_cancelled", "execution_compensated"}, "intents"),
        ):
            page = 1
            while True:
                result = await service.list_page(
                    workspace_id=network.workspace_id, network_id=network.network_id,
                    user_id=actor_id, claim_org_id=None, page=page, page_size=200,
                )
                for item in result.items:
                    if item.status in terminal:
                        continue
                    if label != "intents" or item.status not in {"execution_failed", "execution_completed"}:
                        _conflict(label)
                    from app.modules.intent.service import IntentExecutionService

                    detail = await IntentExecutionService(db=self.db, redis=self.redis).get_intent_detail(
                        workspace_id=network.workspace_id, intent_id=item.intent_id, user_id=actor_id,
                    )
                    if not _verified_intent_restoration(detail, intent_id=item.intent_id, network=network):
                        _conflict(label)
                if page * 200 >= result.total:
                    break
                page += 1
        autonomy = await AutonomyService(self.db, self.redis).snapshot(
            network.network_id, network.workspace_id, history_limit=1,
        )
        if (autonomy.mode != "monitor" or autonomy.active_execution_id is not None
                or autonomy.cancellation_status in {"requested", "uncertain"}
                or "timed_override_unresolved" in autonomy.blocked_reasons):
            _conflict("autonomy or timed overrides")
