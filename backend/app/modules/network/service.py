"""NANFO Backend — Network module service layer.

NetworkService: create/list networks. Validates workspace via OrgService (C5).
DeviceService: add/list devices. Publishes network.device.added event.

C5 enforcement:
  workspace_id is validated by calling WorkspaceService.get_active_workspace(),
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
    CreateDeviceRequest,
    CreateNetworkRequest,
    DeviceListResponse,
    DeviceResponse,
    NetworkListResponse,
    NetworkResponse,
    UpdateDeviceRequest,
)
from app.modules.organization.service import WorkspaceService as OrgWorkspaceService

logger = get_logger(__name__)


class NetworkService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = NetworkRepository(db)
        # C5: WorkspaceService is the Organization module's public service API.
        # NetworkService calls get_active_workspace() — the service-layer boundary —
        # not the Organization module's repository directly.
        # No SQL join between network tables and org tables occurs (ADR-004).
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def create_network(
        self,
        req: CreateNetworkRequest,
        actor_id: str,
        correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None,
    ) -> NetworkResponse:
        if requested_workspace_id is not None and req.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        # C5: Validate workspace via the Organization module's service-layer API.
        # get_active_workspace() raises HTTP 404 if workspace does not exist.
        # No cross-module SQL join is performed — the org tables are queried only
        # inside OrgWorkspaceService using the Organization module's own repository.
        await self._workspace_svc.get_active_workspace(req.workspace_id)

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
        page: int,
        page_size: int,
        requested_workspace_id: uuid.UUID | None = None,
    ) -> NetworkListResponse:
        if requested_workspace_id is not None and workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        await self._workspace_svc.get_active_workspace(workspace_id)
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
    ):
        network = await self._repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        await self._workspace_svc.get_active_workspace(network.workspace_id)
        if requested_workspace_id is not None and network.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return network


class DeviceService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = DeviceRepository(db)
        self._network_repo = NetworkRepository(db)

    async def add_device(
        self,
        network_id: uuid.UUID,
        req: CreateDeviceRequest,
        actor_id: str,
        correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None,
    ) -> DeviceResponse:
        network = await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
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
        page: int,
        page_size: int,
        requested_workspace_id: uuid.UUID | None = None,
    ) -> DeviceListResponse:
        await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
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
    ) -> DeviceResponse:
        network = await self._assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
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
    ):
        network = await self._network_repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        if requested_workspace_id is not None and network.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return network
