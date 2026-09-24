"""Inventory deletion policy. Foreign state is read only through owner query modules.

Network-owned dependencies are checked here; Simulation, Intent and Autonomy answer
through their read-only ``has_blocking_work`` functions (ADR-028 §1.2). Callers run
:meth:`InventoryDeletionService.assert_safe` once before taking inventory locks (fast
fail) and again under the lock, where the answer is authoritative because workflow
creation holds the shared network fence that the inventory lock excludes.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.modules.autonomy import queries as autonomy_queries
from app.modules.intent import queries as intent_queries
from app.modules.network.asset_mapping import normalize_asset_device_mapping
from app.modules.network.models import (
    CampusBuildingRecord,
    CampusModelAssetRecord,
    Device,
    DeviceGroup,
    DeviceGroupMember,
)
from app.modules.network.spatial_models import SpatialSceneRecord
from app.modules.simulation import queries as simulation_queries


def _conflict(resource):
    raise HTTPException(status_code=409, detail={
        "code": "INVENTORY_DEPENDENCIES_ACTIVE",
        "message": f"Remove or resolve active {resource} before deleting inventory.",
    })


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


#: Owner query functions consulted, in order, with their conflict labels.
WORKFLOW_OWNERS = (
    (simulation_queries, "simulations"),
    (intent_queries, "intents"),
    (autonomy_queries, "autonomy or timed overrides"),
)


class InventoryDeletionService:
    def __init__(self, db, redis=None):
        self.db, self.redis = db, redis
        self.repository = InventoryDependencyRepository(db)

    async def assert_safe(self, *, network, actor_id=None, device_id=None):
        await self.repository.assert_safe(network.network_id, device_id)
        await self._assert_workflows_safe(network, actor_id)

    async def _assert_workflows_safe(self, network, actor_id=None):
        network_id = network.network_id if isinstance(network.network_id, uuid.UUID) else uuid.UUID(str(network.network_id))
        for owner, label in WORKFLOW_OWNERS:
            if await owner.has_blocking_work(self.db, network_id=network_id):
                _conflict(label)
