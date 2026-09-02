"""NANFO Backend — Network module service layer.

NetworkService: create/list networks. Validates workspace via OrgService (C5).
DeviceService: add/list devices. Publishes network.device.added event.

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

from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.network.repository import DeviceRepository, NetworkRepository
from app.modules.network.schemas import (
    CampusBuildingListResponse,
    CampusBuildingResponse,
    CreateDeviceRequest,
    CreateNetworkRequest,
    DeviceListResponse,
    DeviceResponse,
    NetworkListResponse,
    NetworkResponse,
    UpdateDeviceRequest,
    UpsertCampusBuildingInput,
    UpsertCampusBuildingsRequest,
)
from app.modules.organization.service import WorkspaceService as OrgWorkspaceService

logger = get_logger(__name__)


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
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        network = await self._repo.create(
            workspace_id=req.workspace_id,
            name=req.name,
            description=req.description,
            cidr=req.cidr,
        )
        await self._db.commit()
        await self._db.refresh(network)

        try:
            await publish_event(
                redis=self._redis,
                event_type="network.network.created",
                source="network",
                payload={
                    "network_id": str(network.network_id),
                    "workspace_id": str(req.workspace_id),
                    "name": network.name,
                    "actor_id": actor_id,
                },
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "network_created_event_publish_failed",
                network_id=str(network.network_id),
                correlation_id=correlation_id,
                error=str(exc),
            )
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
    ):
        network = await self._repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        if requested_workspace_id is not None and network.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        workspace = await self._workspace_svc.assert_workspace_membership(
            workspace_id=network.workspace_id,
            user_id=actor_user_id,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return network

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
        network = await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_id,
            claim_org_id=claim_org_id,
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
        await self._db.commit()
        await self._db.refresh(device)

        # Publish network.device.added — consumed by:
        #   1. AuditLogWriter (audit consumer)
        #   2. TopologyConsumer (Neo4j node writer)
        #   3. WSPushConsumer (topology delta pusher → /ws/topology)
        # Per EventAPI.md §5 and design_package §6
        try:
            await publish_event(
                redis=self._redis,
                event_type="network.device.added",
                source="network",
                payload={
                    "device_id": str(device.device_id),
                    "network_id": str(network_id),
                    "workspace_id": str(network.workspace_id),
                    "hostname": device.hostname,
                    "ip_address": device.ip_address,
                    "device_type": device.device_type,
                    "spatial_ref_id": device.spatial_ref_id,
                    "actor_id": actor_id,
                },
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "network_device_added_event_publish_failed",
                network_id=str(network_id),
                device_id=str(device.device_id),
                correlation_id=correlation_id,
                error=str(exc),
            )
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
        network = await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_id,
            claim_org_id=claim_org_id,
        )

        current = await self._repo.get_by_id(device_id)
        if current is None or current.network_id != network_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")

        if current.spatial_ref_id == req.spatial_ref_id:
            return DeviceResponse.model_validate(current)

        device = await self._repo.update_spatial_ref_id(
            network_id=network_id,
            device_id=device_id,
            spatial_ref_id=req.spatial_ref_id,
        )
        if device is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")

        await self._db.commit()
        await self._db.refresh(device)

        changed_fields = {"spatial_ref_id": device.spatial_ref_id}
        try:
            await publish_event(
                redis=self._redis,
                event_type="network.device.updated",
                source="network",
                payload={
                    "device_id": str(device.device_id),
                    "network_id": str(network_id),
                    "workspace_id": str(network.workspace_id),
                    "changed_fields": changed_fields,
                    "actor_id": actor_id,
                },
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "network_device_updated_event_publish_failed",
                network_id=str(network_id),
                device_id=str(device.device_id),
                correlation_id=correlation_id,
                error=str(exc),
            )
        return DeviceResponse.model_validate(device)

    async def _assert_network_workspace_access(
        self,
        *,
        network_id: uuid.UUID,
        requested_workspace_id: uuid.UUID | None,
        actor_user_id: str,
        claim_org_id: uuid.UUID | None,
    ):
        network = await self._network_repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        if requested_workspace_id is not None and network.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        workspace = await self._workspace_svc.assert_workspace_membership(
            workspace_id=network.workspace_id,
            user_id=actor_user_id,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return network


class CampusBuildingService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        from app.modules.network.repository import CampusBuildingRepository

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
        await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=actor_id,
            claim_org_id=claim_org_id,
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
    ):
        network = await self._network_repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        if requested_workspace_id is not None and network.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        workspace = await self._workspace_svc.assert_workspace_membership(
            workspace_id=network.workspace_id,
            user_id=actor_user_id,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return network
