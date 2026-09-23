"""NANFO Backend — Network module service layer.

NetworkService: create/list networks. Validates workspace via OrgService (C5).
DeviceService: add/list devices. Atomically enqueues inventory lifecycle events.

C5 enforcement:
  workspace_id is validated by calling WorkspaceService.assert_workspace_membership(),
  which is the Organization module's public service-layer API.
  NetworkRepository does NOT join against any Organization module table (ADR-004).
"""

from __future__ import annotations

import uuid

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.network.outbox import NetworkOutboxRepository
from app.modules.network.repository import (
    CampusBuildingRepository,
    CampusModelAssetRepository,
    DeviceGroupRepository,
    DeviceRepository,
    NetworkRepository,
    validate_inventory_page,
)
from app.modules.network.schemas import (
    CampusBuildingListResponse,
    CampusBuildingResponse,
    CampusModelAssetListResponse,
    CreateDeviceRequest,
    CreateNetworkRequest,
    DeviceGroupListResponse,
    DeviceGroupResponse,
    DeviceListResponse,
    DeviceResponse,
    NetworkListResponse,
    NetworkResponse,
    UpdateDeviceRequest,
    UpdateNetworkRequest,
    UpsertCampusBuildingInput,
    UpsertCampusBuildingsRequest,
    UpsertCampusModelAssetRequest,
    UpsertDeviceGroupInput,
    UpsertDeviceGroupsRequest,
)
from app.modules.organization.service import WorkspaceService as OrgWorkspaceService


def _changed_fields(current, req) -> dict:
    changes = {}
    for field, value in req.model_dump(exclude_unset=True).items():
        previous = getattr(current, field)
        if field == "ip_address" and previous is not None:
            previous = str(previous)
        if previous != value:
            changes[field] = value
    return changes


class NetworkService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = NetworkRepository(db)
        self._device_repo = DeviceRepository(db)
        # C5: WorkspaceService is the Organization module's public service API.
        # NetworkService calls assert_workspace_membership() — the service-layer boundary —
        # not the Organization module's repository directly.
        # No SQL join between network tables and org tables occurs (ADR-004).
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def create_network(
        self,
        req: CreateNetworkRequest,
        actor_id: str,
        correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> NetworkResponse:
        if requested_workspace_id is not None and req.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        # C5: Validate workspace via the Organization module's service-layer API.
        # No cross-module SQL join is performed — the org tables are queried only
        # inside OrgWorkspaceService using the Organization module's own repository.
        workspace = await self._workspace_svc.assert_workspace_membership(
            workspace_id=req.workspace_id,
            user_id=actor_id,
            require_write=True,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        network = await self._repo.create(
            workspace_id=req.workspace_id,
            name=req.name,
            description=req.description,
            cidr=req.cidr,
        )
        try:
            await NetworkOutboxRepository(self._db).enqueue(
                network_id=network.network_id,
                event_type="network.network.created",
                payload={
                    "network_id": str(network.network_id),
                    "workspace_id": str(req.workspace_id),
                    "org_id": str(workspace.org_id),
                    "name": network.name,
                    "actor_id": actor_id,
                },
                correlation_id=correlation_id,
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise
        await self._db.refresh(network)
        return NetworkResponse.model_validate(network)

    async def list_networks(
        self,
        workspace_id: uuid.UUID,
        actor_user_id: str,
        page: int,
        page_size: int,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> NetworkListResponse:
        validate_inventory_page(page, page_size)
        if requested_workspace_id is not None and workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        workspace = await self._workspace_svc.assert_workspace_membership(
            workspace_id=workspace_id,
            user_id=actor_user_id,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        rows, total = await self._repo.list_for_workspace(workspace_id, page=page, page_size=page_size)
        return NetworkListResponse(
            items=[NetworkResponse.model_validate(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def update_network(
        self, network_id: uuid.UUID, req: UpdateNetworkRequest, actor_id: str,
        correlation_id: str, requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> NetworkResponse:
        outbox = NetworkOutboxRepository(self._db)
        try:
            await outbox.lock_inventory(network_id)
            network, org_id = await self._authorize_network_workspace_access(
                network_id=network_id, requested_workspace_id=requested_workspace_id,
                actor_user_id=actor_id, claim_org_id=claim_org_id, require_write=True,
            )
            changes = _changed_fields(network, req)
            if not changes:
                result = NetworkResponse.model_validate(network)
                await self._db.rollback()
                return result
            await self._repo.update(network, changes)
            await outbox.enqueue(network_id=network_id, event_type="network.network.updated", payload={
                "network_id": str(network_id), "workspace_id": str(network.workspace_id),
                "org_id": str(org_id), "actor_id": actor_id, "changed_fields": changes,
            }, correlation_id=correlation_id)
            await self._db.commit()
            await self._db.refresh(network)
            return NetworkResponse.model_validate(network)
        except BaseException:
            await self._db.rollback()
            raise

    async def delete_network(
        self, network_id: uuid.UUID, actor_id: str, correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
    ) -> None:
        from app.modules.network.deletion import InventoryDeletionService

        outbox = NetworkOutboxRepository(self._db)
        try:
            await outbox.lock_inventory(network_id)
            network = await self.assert_network_workspace_access(
                network_id=network_id, requested_workspace_id=requested_workspace_id,
                actor_user_id=actor_id, claim_org_id=claim_org_id, require_write=True,
            )
            await InventoryDeletionService(self._db, self._redis).assert_safe(network=network, actor_id=actor_id)
            await self._db.run_sync(lambda session: session.expire_all())
            network, org_id = await self._authorize_network_workspace_access(
                network_id=network_id, requested_workspace_id=requested_workspace_id,
                actor_user_id=actor_id, claim_org_id=claim_org_id, require_write=True,
            )
            await self._repo.soft_delete(network)
            await outbox.enqueue(network_id=network_id, event_type="network.network.deleted", payload={
                "network_id": str(network_id), "workspace_id": str(network.workspace_id),
                "org_id": str(org_id), "actor_id": actor_id,
            }, correlation_id=correlation_id)
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise

    async def get_network(self, network_id: uuid.UUID) -> NetworkResponse:
        network = await self._repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")
        return NetworkResponse.model_validate(network)

    async def assert_network_workspace_access(
        self,
        *,
        network_id: uuid.UUID,
        requested_workspace_id: uuid.UUID | None,
        actor_user_id: str,
        claim_org_id: uuid.UUID | None = None,
        require_write: bool = False,
    ):
        network, _ = await self._authorize_network_workspace_access(
            network_id=network_id, requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_user_id, claim_org_id=claim_org_id, require_write=require_write,
        )
        return network

    async def _authorize_network_workspace_access(
        self, *, network_id: uuid.UUID, requested_workspace_id: uuid.UUID | None,
        actor_user_id: str, claim_org_id: uuid.UUID | None = None, require_write: bool = False,
    ):
        """Return the authorized resource and authoritative tenant as local values."""
        if require_write:
            await self._repo.lock_active(network_id)
        network = await self._repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        if requested_workspace_id is not None and network.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        workspace = await self._workspace_svc.assert_workspace_membership(
            workspace_id=network.workspace_id,
            user_id=actor_user_id,
            require_write=require_write,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return network, workspace.org_id

    async def assert_device_workspace_access(
        self,
        *,
        device_id: uuid.UUID,
        requested_workspace_id: uuid.UUID | None,
        actor_user_id: str,
        claim_org_id: uuid.UUID | None = None,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        device = await self._device_repo.get_by_id(device_id)
        if device is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")

        network = await self.assert_network_workspace_access(
            network_id=device.network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_user_id,
            claim_org_id=claim_org_id,
        )
        return network.network_id, network.workspace_id


class DeviceService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = DeviceRepository(db)
        self._network_repo = NetworkRepository(db)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def add_device(
        self,
        network_id: uuid.UUID,
        req: CreateDeviceRequest,
        actor_id: str,
        correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> DeviceResponse:
        outbox = NetworkOutboxRepository(self._db)
        await outbox.lock_inventory(network_id)
        network, org_id = await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        device = await self._repo.create(
            network_id=network_id,
            hostname=req.hostname,
            ip_address=req.ip_address,
            device_type=req.device_type,
            vendor=req.vendor,
            model=req.model,
            location_hint=req.location_hint,
            spatial_ref_id=req.spatial_ref_id,
        )
        # Durably enqueue network.device.added — consumed by:
        #   1. AuditLogWriter (audit consumer)
        #   2. TopologyConsumer (Neo4j node writer)
        #   3. WSPushConsumer (topology delta pusher → /ws/topology)
        # Per EventAPI.md §5 and design_package §6
        try:
            await outbox.enqueue(
                network_id=network_id,
                event_type="network.device.added",
                payload={
                    "device_id": str(device.device_id),
                    "network_id": str(network_id),
                    "workspace_id": str(network.workspace_id),
                    "org_id": str(org_id),
                    "hostname": device.hostname,
                    "ip_address": str(device.ip_address) if device.ip_address is not None else None,
                    "device_type": device.device_type,
                    "spatial_ref_id": device.spatial_ref_id,
                    "actor_id": actor_id,
                },
                correlation_id=correlation_id,
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise
        await self._db.refresh(device)
        return DeviceResponse.model_validate(device)

    async def list_devices(
        self,
        network_id: uuid.UUID,
        actor_user_id: str,
        page: int,
        page_size: int,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> DeviceListResponse:
        validate_inventory_page(page, page_size)
        await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_user_id,
            claim_org_id=claim_org_id,
        )
        rows, total = await self._repo.list_for_network(network_id, page=page, page_size=page_size)
        return DeviceListResponse(
            items=[DeviceResponse.model_validate(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def update_device_spatial_ref(
        self,
        network_id: uuid.UUID,
        device_id: uuid.UUID,
        req: UpdateDeviceRequest,
        actor_id: str,
        correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> DeviceResponse:
        """Compatibility name retained for existing spatial and internal callers."""
        outbox = NetworkOutboxRepository(self._db)
        await outbox.lock_inventory(network_id)
        network, org_id = await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        current = await self._repo.get_by_id(device_id)
        if current is None or current.network_id != network_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")

        changed_fields = _changed_fields(current, req)
        if not changed_fields:
            result = DeviceResponse.model_validate(current)
            await self._db.rollback()
            return result

        device = await self._repo.update(current, changed_fields)
        if device is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")

        try:
            await outbox.enqueue(
                network_id=network_id,
                event_type="network.device.updated",
                payload={
                    "device_id": str(device.device_id),
                    "network_id": str(network_id),
                    "workspace_id": str(network.workspace_id),
                    "org_id": str(org_id),
                    "changed_fields": changed_fields,
                    "actor_id": actor_id,
                },
                correlation_id=correlation_id,
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise
        await self._db.refresh(device)
        return DeviceResponse.model_validate(device)

    async def delete_device(
        self, network_id: uuid.UUID, device_id: uuid.UUID, actor_id: str, correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
    ) -> None:
        from app.modules.network.deletion import InventoryDeletionService

        outbox = NetworkOutboxRepository(self._db)
        try:
            await outbox.lock_inventory(network_id)
            network, _ = await self._assert_network_workspace_access(
                network_id=network_id, requested_workspace_id=requested_workspace_id,
                actor_user_id=actor_id, claim_org_id=claim_org_id, require_write=True,
            )
            device = await self._repo.lock(device_id)
            if device is None or device.network_id != network_id:
                raise HTTPException(status_code=404, detail="Device not found.")
            await InventoryDeletionService(self._db, self._redis).assert_safe(
                network=network, device_id=device_id, actor_id=actor_id,
            )
            await self._db.run_sync(lambda session: session.expire_all())
            network, org_id = await self._assert_network_workspace_access(
                network_id=network_id, requested_workspace_id=requested_workspace_id,
                actor_user_id=actor_id, claim_org_id=claim_org_id, require_write=True,
            )
            device = await self._repo.get_by_id(device_id)
            await self._repo.soft_delete(device)
            await outbox.enqueue(network_id=network_id, event_type="network.device.deleted", payload={
                "device_id": str(device_id), "network_id": str(network_id),
                "workspace_id": str(network.workspace_id), "org_id": str(org_id),
                "actor_id": actor_id,
            }, correlation_id=correlation_id)
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise

    async def _assert_network_workspace_access(
        self,
        *,
        network_id: uuid.UUID,
        requested_workspace_id: uuid.UUID | None,
        actor_user_id: str,
        claim_org_id: uuid.UUID | None,
        require_write: bool = False,
    ):
        network = await self._network_repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        if requested_workspace_id is not None and network.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        workspace = await self._workspace_svc.assert_workspace_membership(
            workspace_id=network.workspace_id,
            user_id=actor_user_id,
            require_write=require_write,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return network, workspace.org_id


class CampusBuildingService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = CampusBuildingRepository(db)
        self._network_repo = NetworkRepository(db)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def list_buildings(
        self,
        *,
        network_id: uuid.UUID,
        actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> CampusBuildingListResponse:
        await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_user_id,
            claim_org_id=claim_org_id,
        )

        rows = await self._repo.list_for_network(network_id)
        return CampusBuildingListResponse(
            items=[CampusBuildingResponse.model_validate(row) for row in rows],
            total=len(rows),
        )

    async def upsert_buildings(
        self,
        *,
        network_id: uuid.UUID,
        req: UpsertCampusBuildingsRequest,
        actor_id: str,
        correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> CampusBuildingListResponse:
        await self._network_repo.lock_active(network_id)
        await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        upserted: list[CampusBuildingResponse] = []

        if req.replace_existing:
            await self._repo.soft_delete_for_network(network_id)

        for building in req.buildings:
            row = await self._upsert_one(network_id=network_id, building=building)
            upserted.append(CampusBuildingResponse.model_validate(row))

        await self._db.commit()

        return CampusBuildingListResponse(items=upserted, total=len(upserted))

    async def _upsert_one(self, *, network_id: uuid.UUID, building: UpsertCampusBuildingInput):
        existing = await self._repo.get_active_by_network_and_building_id(
            network_id=network_id,
            building_id=building.building_id,
        )

        footprint = [[float(point[0]), float(point[1])] for point in building.footprint]
        if existing is None:
            return await self._repo.create(
                network_id=network_id,
                building_id=building.building_id,
                campus_key=building.campus_key,
                building_key=building.building_key,
                label=building.label,
                geometry=building.geometry,
                x=building.x,
                z=building.z,
                base_y=building.base_y,
                width=building.width,
                depth=building.depth,
                height=building.height,
                floors=building.floors,
                footprint=footprint,
                wall_material=building.wall_material,
                attenuation_db=building.attenuation_db,
                source=building.source,
            )

        return await self._repo.update(
            existing,
            campus_key=building.campus_key,
            building_key=building.building_key,
            label=building.label,
            geometry=building.geometry,
            x=building.x,
            z=building.z,
            base_y=building.base_y,
            width=building.width,
            depth=building.depth,
            height=building.height,
            floors=building.floors,
            footprint=footprint,
            wall_material=building.wall_material,
            attenuation_db=building.attenuation_db,
            source=building.source,
        )

    async def _assert_network_workspace_access(
        self,
        *,
        network_id: uuid.UUID,
        requested_workspace_id: uuid.UUID | None,
        actor_user_id: str,
        claim_org_id: uuid.UUID | None,
        require_write: bool = False,
    ):
        network = await self._network_repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        if requested_workspace_id is not None and network.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        workspace = await self._workspace_svc.assert_workspace_membership(
            workspace_id=network.workspace_id,
            user_id=actor_user_id,
            require_write=require_write,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return network


def _normalize_group_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip().lower()
    return token or None


def _device_matches_functional_group(*, device_type: str | None, functional_group: str) -> bool:
    if not device_type:
        return False

    normalized = device_type.strip().lower()
    if not normalized:
        return False

    if functional_group == "core":
        return "router" in normalized or normalized == "core"
    if functional_group == "distribution":
        return "distribution" in normalized or normalized == "dist"
    if functional_group == "access":
        return "access" in normalized
    if functional_group == "wireless":
        return "wireless" in normalized or normalized.endswith("_ap") or normalized == "ap"
    if functional_group == "security":
        return "security" in normalized or "firewall" in normalized
    if functional_group == "server":
        return "server" in normalized
    return functional_group in normalized


class CampusModelAssetService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis, *, asset_store=None):
        from app.modules.network.asset_storage import LocalAssetStore

        self._asset_store = asset_store or LocalAssetStore()
        self._db = db
        self._redis = redis
        self._repo = CampusModelAssetRepository(db)
        self._network_repo = NetworkRepository(db)
        self._device_repo = DeviceRepository(db)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def list_assets(
        self,
        *,
        network_id: uuid.UUID,
        actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
        include_data: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> CampusModelAssetListResponse:
        await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_user_id,
            claim_org_id=claim_org_id,
        )

        from app.modules.network.asset_io import asset_response, download_path
        from app.modules.network.schemas import CampusModelAssetResponse

        if include_data:
            rows = await self._repo.list_for_network(network_id)
            response = CampusModelAssetListResponse(
                items=[await asset_response(self._asset_store, row) for row in rows], total=len(rows),
            )
        else:
            rows, total = await self._repo.list_metadata_for_network(network_id, page=page, page_size=page_size)
            items = [CampusModelAssetResponse.model_validate(row) for row in rows]
            for item in items:
                item.download_path = download_path(item)
            response = CampusModelAssetListResponse(items=items, total=total, page=page, page_size=page_size)
        self._db.expire_all()
        await self._assert_network_workspace_access(
            network_id=network_id, actor_user_id=actor_user_id,
            requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
        )
        return response

    async def download_asset(
        self, *, network_id: uuid.UUID, asset_id: uuid.UUID, actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
    ) -> tuple[bytes, str]:
        from app.modules.network.asset_io import read_body, storage_call

        await self._assert_network_workspace_access(
            network_id=network_id, actor_user_id=actor_user_id,
            requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
        )
        row = await self._repo.get_scoped(network_id, asset_id)
        if row is None:
            raise HTTPException(status_code=404, detail={
                "code": "CAMPUS_MODEL_ASSET_NOT_FOUND", "message": "Campus model asset not found.",
            })
        body = await storage_call(read_body, self._asset_store, row)
        digest = row.model_sha256
        self._db.expire_all()
        await self._assert_network_workspace_access(
            network_id=network_id, actor_user_id=actor_user_id,
            requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
        )
        if await self._repo.get_scoped(network_id, asset_id) is None:
            raise HTTPException(status_code=404, detail="Campus model asset not found.")
        return body, digest

    async def retire_asset(
        self, *, network_id: uuid.UUID, asset_id: uuid.UUID, actor_id: str,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
    ) -> None:
        """Retire current metadata without touching content-addressed bytes or history."""
        try:
            await self._assert_network_workspace_access(
                network_id=network_id, actor_user_id=actor_id, require_write=True,
                requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
            )
            await self._repo.lock_network(network_id)
            self._db.expire_all()
            await self._assert_network_workspace_access(
                network_id=network_id, actor_user_id=actor_id, require_write=True,
                requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
            )
            row = await self._repo.get_scoped(network_id, asset_id)
            if row is None:
                raise HTTPException(status_code=404, detail={
                    "code": "CAMPUS_MODEL_ASSET_NOT_FOUND", "message": "Campus model asset not found.",
                })
            await self._repo.soft_delete(row)
            self._db.expire_all()
            await self._assert_network_workspace_access(
                network_id=network_id, actor_user_id=actor_id, require_write=True,
                requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise

    async def upsert_asset(
        self,
        *,
        network_id: uuid.UUID,
        req: UpsertCampusModelAssetRequest,
        actor_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> CampusModelAssetListResponse:
        from app.modules.network.asset_io import asset_response, storage_call
        from app.modules.network.asset_mapping import normalize_asset_device_mapping
        from app.modules.network.asset_storage import decode_inline

        await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        try:
            await self._repo.lock_network(network_id)
            # Reload current owner authority after a potentially blocking lock.
            self._db.expire_all()
            await self._assert_network_workspace_access(
                network_id=network_id, actor_user_id=actor_id,
                requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id, require_write=True,
            )
            mapping = normalize_asset_device_mapping(req.mapping_by_device_id)
            await self._validate_mapping_device_ids(network_id=network_id, mapping_by_device_id=mapping)
            body = decode_inline(req.model_data_base64, req.model_sha256, req.model_size_bytes)
            await storage_call(self._asset_store.put, body, req.model_sha256, req.model_size_bytes)
            self._db.expire_all()
            await self._assert_network_workspace_access(
                network_id=network_id, actor_user_id=actor_id,
                requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id, require_write=True,
            )
            existing = None if req.replace_existing else await self._repo.get_latest_for_network(network_id)
            same_body = (existing is not None and existing.model_sha256 == req.model_sha256
                         and existing.model_size_bytes == req.model_size_bytes)
            registration = req.registration.model_dump(mode="json") if req.registration is not None else None
            if same_body and "registration" not in req.model_fields_set:
                registration = existing.registration
            values = dict(
                model_file_name=req.model_file_name, model_mime_type=req.model_mime_type,
                model_data_base64=None, model_sha256=req.model_sha256, model_size_bytes=req.model_size_bytes,
                mapping_by_device_id=mapping, storage_backend="local_cas", registration=registration,
                source=req.source.strip().lower() if isinstance(req.source, str) and req.source.strip() else None,
            )
            if req.replace_existing:
                await self._repo.soft_delete_for_network(network_id)
            if same_body:
                row = await self._repo.update(existing, **values)
            else:
                row = await self._repo.create(network_id=network_id, **values)
            response = await asset_response(self._asset_store, row)
            # Response construction awaits a disk read after persistence flushes.
            # Reload authority after that last blocking operation, before commit.
            self._db.expire_all()
            await self._assert_network_workspace_access(
                network_id=network_id, actor_user_id=actor_id,
                requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id, require_write=True,
            )
            await self._db.commit()
            return CampusModelAssetListResponse(items=[response], total=1)
        except BaseException:
            await self._db.rollback()
            raise

    async def _validate_mapping_device_ids(
        self,
        *,
        network_id: uuid.UUID,
        mapping_by_device_id: dict[str, str],
    ) -> None:
        if not mapping_by_device_id:
            return

        parsed_device_ids: list[uuid.UUID] = []
        for device_id in mapping_by_device_id:
            try:
                parsed_device_ids.append(uuid.UUID(device_id))
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "CAMPUS_MODEL_ASSET_MAPPING_DEVICE_ID_INVALID",
                        "message": f"mapping_by_device_id contains invalid device_id '{device_id}'.",
                    },
                ) from exc

        known_ids = await self._device_repo.list_device_ids_for_network(
            network_id=network_id,
            device_ids=parsed_device_ids,
        )
        missing = sorted([str(device_id) for device_id in parsed_device_ids if device_id not in known_ids])
        if missing:
            preview = ", ".join(missing[:5])
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "CAMPUS_MODEL_ASSET_MAPPING_DEVICE_NOT_FOUND",
                    "message": (
                        "mapping_by_device_id references devices that are not active in this network: "
                        f"{preview}"
                    ),
                },
            )

    async def _assert_network_workspace_access(
        self,
        *,
        network_id: uuid.UUID,
        requested_workspace_id: uuid.UUID | None,
        actor_user_id: str,
        claim_org_id: uuid.UUID | None,
        require_write: bool = False,
    ):
        network = await self._network_repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        if requested_workspace_id is not None and network.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        workspace = await self._workspace_svc.assert_workspace_membership(
            workspace_id=network.workspace_id,
            user_id=actor_user_id,
            require_write=require_write,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return network


class DeviceGroupService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = DeviceGroupRepository(db)
        self._network_repo = NetworkRepository(db)
        self._device_repo = DeviceRepository(db)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def list_groups(
        self,
        *,
        network_id: uuid.UUID,
        actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> DeviceGroupListResponse:
        await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_user_id,
            claim_org_id=claim_org_id,
        )
        rows = await self._repo.list_groups_for_network(network_id)
        members_by_group_id = await self._repo.list_members_for_group_ids([row.device_group_id for row in rows])

        return DeviceGroupListResponse(
            items=[
                self._to_group_response(
                    row,
                    members_by_group_id.get(row.device_group_id, []),
                )
                for row in rows
            ],
            total=len(rows),
        )

    async def upsert_groups(
        self,
        *,
        network_id: uuid.UUID,
        req: UpsertDeviceGroupsRequest,
        actor_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> DeviceGroupListResponse:
        await self._network_repo.lock_active(network_id)
        await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        devices = await self._device_repo.list_active_for_network(network_id)
        devices_by_id = {device.device_id: device for device in devices}

        if req.replace_existing:
            await self._repo.soft_delete_for_network(network_id)

        upserted_rows = []
        for group in req.groups:
            device_ids = self._resolve_group_device_ids(
                group=group,
                network_id=network_id,
                devices=devices,
                devices_by_id=devices_by_id,
            )

            existing = await self._repo.get_active_by_group_key(
                network_id=network_id,
                group_key=group.group_key,
            )
            if existing is None:
                row = await self._repo.create_group(
                    network_id=network_id,
                    group_key=group.group_key,
                    name=group.name,
                    group_type=group.group_type,
                    description=group.description,
                    selector=dict(group.selector),
                )
            else:
                row = await self._repo.update_group(
                    existing,
                    name=group.name,
                    group_type=group.group_type,
                    description=group.description,
                    selector=dict(group.selector),
                )

            await self._repo.replace_members(group_id=row.device_group_id, device_ids=device_ids)
            upserted_rows.append(row)

        await self._db.commit()

        members_by_group_id = await self._repo.list_members_for_group_ids([row.device_group_id for row in upserted_rows])
        return DeviceGroupListResponse(
            items=[
                self._to_group_response(
                    row,
                    members_by_group_id.get(row.device_group_id, []),
                )
                for row in upserted_rows
            ],
            total=len(upserted_rows),
        )

    @staticmethod
    def _to_group_response(row, member_ids: list[uuid.UUID]) -> DeviceGroupResponse:
        selector = dict(row.selector) if isinstance(row.selector, dict) else {}
        return DeviceGroupResponse(
            device_group_id=row.device_group_id,
            network_id=row.network_id,
            group_key=row.group_key,
            name=row.name,
            group_type=row.group_type,
            description=row.description,
            selector={str(key): str(value) for key, value in selector.items()},
            device_ids=sorted(member_ids),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _resolve_group_device_ids(
        self,
        *,
        group: UpsertDeviceGroupInput,
        network_id: uuid.UUID,
        devices: list,
        devices_by_id: dict[uuid.UUID, object],
    ) -> list[uuid.UUID]:
        explicit_ids = list(group.device_ids)
        unknown_ids = [str(device_id) for device_id in explicit_ids if device_id not in devices_by_id]
        if unknown_ids:
            preview = ", ".join(unknown_ids[:5])
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "DEVICE_GROUP_DEVICE_NOT_FOUND",
                    "message": (
                        "device_ids contains values that are not active in this network "
                        f"({network_id}): {preview}"
                    ),
                },
            )

        site_prefix = _normalize_group_token(group.selector.get("site_prefix"))
        functional_group = _normalize_group_token(group.selector.get("functional_group"))
        operational_group = _normalize_group_token(group.selector.get("operational_group"))
        device_type_selector = _normalize_group_token(group.selector.get("device_type"))

        has_selector_filters = any(
            selector_value is not None
            for selector_value in (
                site_prefix,
                functional_group,
                operational_group,
                device_type_selector,
            )
        )
        if not has_selector_filters:
            return sorted(set(explicit_ids))

        selected: set[uuid.UUID] = set(explicit_ids)
        for device in devices:
            spatial_ref_id = getattr(device, "spatial_ref_id", None)
            if site_prefix is not None:
                normalized_spatial = spatial_ref_id.strip().lower() if isinstance(spatial_ref_id, str) else ""
                if not normalized_spatial.startswith(site_prefix):
                    continue

            normalized_device_type = getattr(device, "device_type", None)
            if device_type_selector is not None:
                candidate = normalized_device_type.strip().lower() if isinstance(normalized_device_type, str) else ""
                if candidate != device_type_selector:
                    continue

            if functional_group is not None and not _device_matches_functional_group(
                device_type=normalized_device_type,
                functional_group=functional_group,
            ):
                continue

            if operational_group is not None:
                location_hint = getattr(device, "location_hint", None)
                normalized_location = location_hint.strip().lower() if isinstance(location_hint, str) else ""
                if operational_group not in normalized_location:
                    continue

            selected.add(device.device_id)

        return sorted(selected)

    async def _assert_network_workspace_access(
        self,
        *,
        network_id: uuid.UUID,
        requested_workspace_id: uuid.UUID | None,
        actor_user_id: str,
        claim_org_id: uuid.UUID | None,
        require_write: bool = False,
    ):
        network = await self._network_repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        if requested_workspace_id is not None and network.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        workspace = await self._workspace_svc.assert_workspace_membership(
            workspace_id=network.workspace_id,
            user_id=actor_user_id,
            require_write=require_write,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return network
