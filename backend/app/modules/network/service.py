"""NANFO Backend — Network module service layer.

NetworkService: create/list/update/delete networks. Validates workspace via OrgService (C5).
DeviceService: add/list/update/delete devices. Atomically enqueues inventory lifecycle events.
CampusBuildingService / CampusModelAssetService / DeviceGroupService: network-owned
Digital Twin persistence with same-transaction Identity audits (ADR-028).

C5 enforcement:
  workspace_id is validated by calling WorkspaceService.assert_workspace_membership(),
  which is the Organization module's public service-layer API, through the single
  NetworkAccessGuard. NetworkRepository does NOT join against any Organization table.
  The Organization module is imported lazily (no import-time cycle).

Locking: every mutation authorizes *before* requesting a Network lock and re-checks
authority after the lock is granted (``NetworkAccessGuard``). Rows whose server-side
``updated_at`` changes are reloaded before responses are built (no async lazy loads).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http_cache import digest_etag, if_none_match_satisfied
from app.core.logging import get_logger
from app.modules.identity.service import append_audit_log
from app.modules.network.access import LockPolicy, NetworkAccessGuard, NetworkGrant, forbidden, workspace_service
from app.modules.network.deletion import InventoryDeletionService
from app.modules.network.device_types import matches_functional_group, normalize_device_type
from app.modules.network.outbox import NetworkOutboxRepository
from app.modules.network.repository import (
    CAMPUS_BUILDING_FIELDS,
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

logger = get_logger(__name__)

#: include_data=true bounds (C4): small pages and a bounded aggregate response body.
INLINE_ASSET_MAX_PAGE_SIZE = 10
INLINE_ASSET_MAX_AGGREGATE_BYTES = 32 * 1024 * 1024
_AUDIT_ID_PREVIEW = 50


def _changed_fields(current, req) -> dict:
    changes = {}
    for field, value in req.model_dump(exclude_unset=True).items():
        previous = getattr(current, field)
        if field == "ip_address" and previous is not None:
            previous = str(previous)
        if previous != value:
            changes[field] = value
    return changes


def _actor_uuid(actor_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(actor_id))
    except (TypeError, ValueError, AttributeError):
        raise forbidden() from None


async def _audit(
    db: AsyncSession, *, event_type: str, actor_id: str, network_id: uuid.UUID, resource_type: str,
    resource_id: uuid.UUID, correlation_id: str | None, grant: NetworkGrant, metadata: dict,
) -> None:
    """Append the Identity audit in the caller's transaction (commits with the mutation)."""
    await append_audit_log(
        db=db, event_type=event_type, actor_id=_actor_uuid(actor_id), resource_type=resource_type,
        resource_id=resource_id, correlation_id=correlation_id, org_id=grant.org_id,
        metadata={"network_id": str(network_id), "workspace_id": str(grant.workspace_id), **metadata},
    )


class _GuardedService:
    """Shared construction of the single NetworkAccessGuard for Network services."""

    _db: AsyncSession
    _network_repo: NetworkRepository
    _workspace_svc: object

    @property
    def guard(self) -> NetworkAccessGuard:
        # Built per use from current collaborators so injected fakes stay authoritative.
        return NetworkAccessGuard(self._db, networks=self._network_repo, workspaces=self._workspace_svc)

    def _access(self, *, network_id, actor_user_id, requested_workspace_id=None, claim_org_id=None,
                require_write=False) -> dict:
        return {"network_id": network_id, "actor_user_id": actor_user_id,
                "requested_workspace_id": requested_workspace_id, "claim_org_id": claim_org_id,
                "require_write": require_write}


@dataclass(frozen=True, slots=True)
class ReconcileScope:
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    watermark: int


class NetworkService(_GuardedService):

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = NetworkRepository(db)
        self._device_repo = DeviceRepository(db)
        # C5: WorkspaceService is the Organization module's public service API.
        # No SQL join between network tables and org tables occurs (ADR-004).
        self._workspace_svc = workspace_service(db, redis)

    @property
    def _network_repo(self) -> NetworkRepository:  # type: ignore[override]
        return self._repo

    async def create_network(
        self,
        req: CreateNetworkRequest,
        actor_id: str,
        correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> NetworkResponse:
        # C5: Validate workspace via the Organization module's service-layer API,
        # through the single guard (claims only narrow access).
        workspace = await self.guard.check_workspace(
            workspace_id=req.workspace_id, actor_user_id=actor_id, requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id, require_write=True,
        )

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
        await self.guard.check_workspace(
            workspace_id=workspace_id, actor_user_id=actor_user_id, requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id,
        )

        rows, total = await self._repo.list_for_workspace(workspace_id, page=page, page_size=page_size)
        return NetworkListResponse(
            items=[NetworkResponse.model_validate(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def has_active_networks(self, *, workspace_id: uuid.UUID, actor_user_id: str) -> bool:
        """Organization's ``WorkspaceInventory`` port (breaks the org↔network cycle).

        Organization asks this narrow question (lazily importing Network) before a
        workspace deletion instead of paging networks. The actor must be a member
        of the workspace; the answer is one indexed existence probe.
        """
        await self.guard.check_workspace(workspace_id=workspace_id, actor_user_id=actor_user_id)
        return await self._repo.has_active_for_workspace(workspace_id)

    async def update_network(
        self, network_id: uuid.UUID, req: UpdateNetworkRequest, actor_id: str,
        correlation_id: str, requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> NetworkResponse:
        try:
            grant = await self.guard.authorize(**self._access(
                network_id=network_id, actor_user_id=actor_id, requested_workspace_id=requested_workspace_id,
                claim_org_id=claim_org_id, require_write=True,
            ), lock=LockPolicy.INVENTORY)
            network = grant.network
            changes = _changed_fields(network, req)
            if not changes:
                result = NetworkResponse.model_validate(network)
                await self._db.rollback()
                return result
            await self._repo.update(network, changes)
            await NetworkOutboxRepository(self._db).enqueue(
                network_id=network_id, event_type="network.network.updated", payload={
                    "network_id": str(network_id), "workspace_id": str(network.workspace_id),
                    "org_id": str(grant.org_id), "actor_id": actor_id, "changed_fields": changes,
                }, correlation_id=correlation_id,
            )
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
        access = self._access(network_id=network_id, actor_user_id=actor_id, require_write=True,
                              requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        deletion = InventoryDeletionService(self._db, self._redis)
        try:
            grant = await self.guard.authorize(**access)
            # Fast fail before any lock; the answer under the lock below is authoritative.
            await deletion.assert_safe(network=grant.network, actor_id=actor_id)
            grant = await self.guard.lock_and_check(**access, lock=LockPolicy.INVENTORY)
            await deletion.assert_safe(network=grant.network, actor_id=actor_id)
            await self._repo.soft_delete(grant.network)
            await NetworkOutboxRepository(self._db).enqueue(
                network_id=network_id, event_type="network.network.deleted", payload={
                    "network_id": str(network_id), "workspace_id": str(grant.workspace_id),
                    "org_id": str(grant.org_id), "actor_id": actor_id,
                }, correlation_id=correlation_id,
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise

    async def authorize_network(
        self, *, network_id: uuid.UUID, actor_user_id: str, requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None, require_write: bool = False, lock: LockPolicy = LockPolicy.NONE,
    ) -> NetworkGrant:
        """Public guard entry point returning the network and authoritative org_id."""
        return await self.guard.authorize(**self._access(
            network_id=network_id, actor_user_id=actor_user_id, requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id, require_write=require_write,
        ), lock=lock)

    async def assert_network_workspace_access(
        self,
        *,
        network_id: uuid.UUID,
        requested_workspace_id: uuid.UUID | None,
        actor_user_id: str,
        claim_org_id: uuid.UUID | None = None,
        require_write: bool = False,
    ):
        """Compatibility contract for other modules.

        Write authority additionally holds the shared parent fence (``FOR SHARE``)
        until the caller's transaction ends, serializing workflow creation against
        inventory deletion. Authority is checked before and after that lock.
        """
        grant = await self.authorize_network(
            network_id=network_id, actor_user_id=actor_user_id, requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id, require_write=require_write,
            lock=LockPolicy.SHARE if require_write else LockPolicy.NONE,
        )
        return grant.network

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

    async def get_device_for_owner(
        self, *, device_id: uuid.UUID, actor_user_id: str, network_id: uuid.UUID | None = None,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
    ) -> DeviceResponse:
        """Public read of ONE active device, including ``ip_address`` and ``status``.

        For owner-bound integrations (collector bindings, emulation checks) that must
        verify one device without paging inventory. The actor's current (read)
        authority over the device's network is checked; when ``network_id`` is given
        it is authorized first and the device must belong to it. Absent, deleted or
        foreign devices are 404 ``Device not found.``; no lock is taken.
        """
        if network_id is not None:
            await self.guard.check(network_id=network_id, actor_user_id=actor_user_id,
                                   requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        device = await self._device_repo.get_by_id(device_id)
        if device is None or (network_id is not None and device.network_id != network_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")
        if network_id is None:
            await self.guard.check(network_id=device.network_id, actor_user_id=actor_user_id,
                                   requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        return DeviceResponse.model_validate(device)

    async def get_devices_for_owner(
        self, *, network_id: uuid.UUID, device_ids: Sequence[uuid.UUID], actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
    ) -> dict[uuid.UUID, DeviceResponse]:
        """Authorize once, then read the ACTIVE devices of ``network_id`` among ``device_ids``.

        Batch form of :meth:`get_device_for_owner` (at most ``MAX_OWNER_DEVICE_READ``
        ids). Missing, deleted and foreign devices are simply absent from the result,
        so callers decide how to fail. No lock is taken.
        """
        await self.guard.check(network_id=network_id, actor_user_id=actor_user_id,
                               requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        rows = await self._device_repo.list_active_by_ids(network_id, device_ids)
        return {row.device_id: DeviceResponse.model_validate(row) for row in rows}

    async def reconcile_scope(
        self, *, network_id: uuid.UUID, actor_user_id: str, requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> ReconcileScope:
        """Authorize a topology reconcile and read its projection watermark.

        The watermark is read under the inventory lock (no in-flight event of this
        network), then the transaction ends before any graph or Redis I/O.
        """
        try:
            grant = await self.authorize_network(
                network_id=network_id, actor_user_id=actor_user_id, requested_workspace_id=requested_workspace_id,
                claim_org_id=claim_org_id, require_write=True, lock=LockPolicy.INVENTORY,
            )
            scope = ReconcileScope(grant.network_id, grant.workspace_id,
                                   await NetworkOutboxRepository(self._db).watermark())
        finally:
            await self._db.rollback()
        return scope


class DeviceService(_GuardedService):

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = DeviceRepository(db)
        self._network_repo = NetworkRepository(db)
        self._workspace_svc = workspace_service(db, redis)

    async def add_device(
        self,
        network_id: uuid.UUID,
        req: CreateDeviceRequest,
        actor_id: str,
        correlation_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> DeviceResponse:
        try:
            grant = await self.guard.authorize(**self._access(
                network_id=network_id, actor_user_id=actor_id, requested_workspace_id=requested_workspace_id,
                claim_org_id=claim_org_id, require_write=True,
            ), lock=LockPolicy.INVENTORY)
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
            # Durably enqueue network.device.added — consumed by audit, topology
            # (Neo4j projection) and ws-push (EventAPI.md §5).
            await NetworkOutboxRepository(self._db).enqueue(
                network_id=network_id,
                event_type="network.device.added",
                payload={
                    "device_id": str(device.device_id),
                    "network_id": str(network_id),
                    "workspace_id": str(grant.workspace_id),
                    "org_id": str(grant.org_id),
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
        await self.guard.authorize(**self._access(
            network_id=network_id, actor_user_id=actor_user_id, requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id,
        ))
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
        try:
            grant = await self.guard.authorize(**self._access(
                network_id=network_id, actor_user_id=actor_id, requested_workspace_id=requested_workspace_id,
                claim_org_id=claim_org_id, require_write=True,
            ), lock=LockPolicy.INVENTORY)
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
            await NetworkOutboxRepository(self._db).enqueue(
                network_id=network_id,
                event_type="network.device.updated",
                payload={
                    "device_id": str(device.device_id),
                    "network_id": str(network_id),
                    "workspace_id": str(grant.workspace_id),
                    "org_id": str(grant.org_id),
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
        access = self._access(network_id=network_id, actor_user_id=actor_id, require_write=True,
                              requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        deletion = InventoryDeletionService(self._db, self._redis)
        try:
            grant = await self.guard.authorize(**access)
            device = await self._repo.get_by_id(device_id)
            if device is None or device.network_id != network_id:
                raise HTTPException(status_code=404, detail="Device not found.")
            # Fast fail before any lock; the answer under the locks below is authoritative.
            await deletion.assert_safe(network=grant.network, device_id=device_id, actor_id=actor_id)
            grant = await self.guard.lock_and_check(**access, lock=LockPolicy.INVENTORY)
            device = await self._repo.lock(device_id)
            if device is None or device.network_id != network_id:
                raise HTTPException(status_code=404, detail="Device not found.")
            await deletion.assert_safe(network=grant.network, device_id=device_id, actor_id=actor_id)
            await self._repo.soft_delete(device)
            await NetworkOutboxRepository(self._db).enqueue(
                network_id=network_id, event_type="network.device.deleted", payload={
                    "device_id": str(device_id), "network_id": str(network_id),
                    "workspace_id": str(grant.workspace_id), "org_id": str(grant.org_id),
                    "actor_id": actor_id,
                }, correlation_id=correlation_id,
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise


def _building_values(building: UpsertCampusBuildingInput) -> dict:
    values = {name: getattr(building, name) for name in CAMPUS_BUILDING_FIELDS}
    values["footprint"] = [[float(point[0]), float(point[1])] for point in building.footprint]
    values["building_id"] = building.building_id
    return values


class CampusBuildingService(_GuardedService):

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = CampusBuildingRepository(db)
        self._network_repo = NetworkRepository(db)
        self._workspace_svc = workspace_service(db, redis)

    async def list_buildings(
        self,
        *,
        network_id: uuid.UUID,
        actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> CampusBuildingListResponse:
        await self.guard.authorize(**self._access(
            network_id=network_id, actor_user_id=actor_user_id, requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id,
        ))
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
        correlation_id: str | None = None,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> CampusBuildingListResponse:
        """Upsert in place on the unique active ``(network_id, building_id)`` index.

        ``replace_existing`` additionally soft-deletes active buildings absent from
        the request; matching rows keep their identity (no delete/reinsert churn).
        """
        # A repeated building_id in one request keeps its last values (first position).
        latest: dict[str, UpsertCampusBuildingInput] = {}
        for building in req.buildings:
            latest[building.building_id] = building
        order = list(latest)
        try:
            grant = await self.guard.authorize(**self._access(
                network_id=network_id, actor_user_id=actor_id, requested_workspace_id=requested_workspace_id,
                claim_org_id=claim_org_id, require_write=True,
            ), lock=LockPolicy.INVENTORY)
            previous = await self._repo.active_building_ids(network_id)
            if latest:
                await self._repo.upsert_many(
                    network_id=network_id, buildings=[_building_values(latest[key]) for key in order],
                )
            retired = await self._repo.soft_delete_absent(network_id, order) if req.replace_existing else 0
            # Reload committed-to-be state: server-side updated_at is never lazy-loaded.
            rows = await self._repo.list_active_by_building_ids(network_id, order)
            items = [CampusBuildingResponse.model_validate(rows[key]) for key in order]
            await _audit(
                self._db, event_type="network.campus_buildings.upserted", actor_id=actor_id, network_id=network_id,
                resource_type="network_campus_buildings", resource_id=network_id, correlation_id=correlation_id,
                grant=grant, metadata={
                    "replace_existing": req.replace_existing, "upserted": len(order),
                    "created": sum(1 for key in order if key not in previous),
                    "updated": sum(1 for key in order if key in previous), "retired": retired,
                    "building_ids": order[:_AUDIT_ID_PREVIEW],
                },
            )
            await self._db.commit()
            return CampusBuildingListResponse(items=items, total=len(items))
        except BaseException:
            await self._db.rollback()
            raise


def _normalize_group_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip().lower()
    return token or None


def _assert_inline_budget(sizes) -> None:
    """C4: ``include_data=true`` pages carry at most 32 MiB of asset bodies (else 400)."""
    if sum(sizes) > INLINE_ASSET_MAX_AGGREGATE_BYTES:
        raise HTTPException(status_code=400, detail={
            "code": "CAMPUS_MODEL_ASSET_INLINE_LIMIT_EXCEEDED",
            "message": "Inline asset bodies exceed 32 MiB; use metadata pages and downloads.",
        })


class CampusModelAssetService(_GuardedService):

    def __init__(self, db: AsyncSession, redis: aioredis.Redis, *, asset_store=None):
        from app.modules.network.asset_storage import LocalAssetStore

        self._asset_store = asset_store or LocalAssetStore()
        self._db = db
        self._redis = redis
        self._repo = CampusModelAssetRepository(db)
        self._network_repo = NetworkRepository(db)
        self._device_repo = DeviceRepository(db)
        self._workspace_svc = workspace_service(db, redis)

    async def list_assets(
        self,
        *,
        network_id: uuid.UUID,
        actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
        include_data: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> CampusModelAssetListResponse:
        """Metadata pages by default (C4). ``include_data`` is bounded and explicit."""
        from app.modules.network.asset_io import asset_response, metadata_response

        access = self._access(network_id=network_id, actor_user_id=actor_user_id,
                              requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        await self.guard.check(**access)
        if include_data:
            if page_size > INLINE_ASSET_MAX_PAGE_SIZE:
                raise HTTPException(status_code=400, detail={
                    "code": "CAMPUS_MODEL_ASSET_INLINE_PAGE_TOO_LARGE",
                    "message": f"include_data=true requires page_size <= {INLINE_ASSET_MAX_PAGE_SIZE}.",
                })
            # Size the page from metadata first, so no body (nor legacy inline base64)
            # is loaded for a page that exceeds the aggregate cap.
            preview, _ = await self._repo.list_metadata_for_network(network_id, page=page, page_size=page_size)
            _assert_inline_budget(int(row["model_size_bytes"] or 0) for row in preview)
            rows, total = await self._repo.list_page_for_network(network_id, page=page, page_size=page_size)
            # The page may have shifted between the two reads: re-check what was loaded.
            _assert_inline_budget(int(row.model_size_bytes or 0) for row in rows)
            items = [await asset_response(self._asset_store, row) for row in rows]
        else:
            rows, total = await self._repo.list_metadata_for_network(network_id, page=page, page_size=page_size)
            items = [metadata_response(row) for row in rows]
        # Authority may have changed during the (possibly blocking) reads above.
        await self.guard.check(**access)
        return CampusModelAssetListResponse(items=items, total=total, page=page, page_size=page_size)

    async def download_asset(
        self, *, network_id: uuid.UUID, asset_id: uuid.UUID, actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
        if_none_match: str | None = None,
    ) -> tuple[bytes | None, str]:
        """Return ``(verified body, sha256)``; body is None when ``If-None-Match`` matches."""
        from app.modules.network.asset_io import read_body, storage_call

        access = self._access(network_id=network_id, actor_user_id=actor_user_id,
                              requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        await self.guard.check(**access)
        row = await self._repo.get_scoped(network_id, asset_id)
        if row is None:
            raise HTTPException(status_code=404, detail={
                "code": "CAMPUS_MODEL_ASSET_NOT_FOUND", "message": "Campus model asset not found.",
            })
        digest = row.model_sha256
        if if_none_match:
            try:
                if if_none_match_satisfied(if_none_match, digest_etag(digest)):
                    return None, digest
            except ValueError:
                pass  # corrupt stored digest: fall through to the verified read (fails closed)
        body = await storage_call(read_body, self._asset_store, row)
        # Authority and existence are re-read after the blocking storage read.
        await self.guard.check(**access)
        if await self._repo.get_scoped(network_id, asset_id) is None:
            raise HTTPException(status_code=404, detail="Campus model asset not found.")
        return body, digest

    async def retire_asset(
        self, *, network_id: uuid.UUID, asset_id: uuid.UUID, actor_id: str,
        requested_workspace_id: uuid.UUID | None = None, claim_org_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Retire current metadata without touching content-addressed bytes or history."""
        access = self._access(network_id=network_id, actor_user_id=actor_id, require_write=True,
                              requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        try:
            await self.guard.authorize(**access, lock=LockPolicy.EXCLUSIVE)
            row = await self._repo.get_scoped(network_id, asset_id)
            if row is None:
                raise HTTPException(status_code=404, detail={
                    "code": "CAMPUS_MODEL_ASSET_NOT_FOUND", "message": "Campus model asset not found.",
                })
            digest, size = row.model_sha256, row.model_size_bytes
            await self._repo.soft_delete(row)
            # The flush can wait on row locks: authority is re-read before commit.
            grant = await self.guard.check(**access)
            await _audit(
                self._db, event_type="network.campus_model_asset.retired", actor_id=actor_id, network_id=network_id,
                resource_type="campus_model_asset", resource_id=asset_id, correlation_id=correlation_id,
                grant=grant, metadata={"asset_id": str(asset_id), "model_sha256": digest, "model_size_bytes": size},
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
        correlation_id: str | None = None,
    ) -> CampusModelAssetListResponse:
        """Store bytes outside the DB, persist metadata, and return metadata only (C4)."""
        from app.modules.network.asset_io import decode_upload, metadata_response, storage_call
        from app.modules.network.asset_mapping import normalize_asset_device_mapping

        access = self._access(network_id=network_id, actor_user_id=actor_id, require_write=True,
                              requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        published = False
        try:
            await self.guard.authorize(**access)
            mapping = normalize_asset_device_mapping(req.mapping_by_device_id)
            # Decode + hash exactly once, off the event loop, before any lock is held.
            body = await decode_upload(req)
            await self.guard.lock_and_check(**access, lock=LockPolicy.EXCLUSIVE)
            await self._validate_mapping_device_ids(network_id=network_id, mapping_by_device_id=mapping)
            existing = None if req.replace_existing else await self._repo.get_latest_for_network(network_id)
            same_body = (existing is not None and existing.model_sha256 == req.model_sha256
                         and existing.model_size_bytes == req.model_size_bytes)
            await self._assert_network_quota(network_id=network_id, req=req, same_body=same_body)
            # Fences blob publication against garbage collection until this commits.
            await self._repo.lock_digest(req.model_sha256)
            published = await storage_call(
                self._asset_store.put, body, req.model_sha256, req.model_size_bytes, verified=True,
            )
            # Authority may have changed during the blocking storage write.
            await self.guard.check(**access)
            registration = req.registration.model_dump(mode="json") if req.registration is not None else None
            if same_body and "registration" not in req.model_fields_set:
                registration = existing.registration
            values = dict(
                model_file_name=req.model_file_name, model_mime_type=req.model_mime_type,
                model_data_base64=None, model_sha256=req.model_sha256, model_size_bytes=req.model_size_bytes,
                mapping_by_device_id=mapping, storage_backend="local_cas", registration=registration,
                source=req.source.strip().lower() if isinstance(req.source, str) and req.source.strip() else None,
            )
            retired = await self._repo.soft_delete_for_network(network_id) if req.replace_existing else 0
            if same_body:
                row = await self._repo.update(existing, **values)
            else:
                row = await self._repo.create(network_id=network_id, **values)
            # updated_at/created_at are server-generated: reload before serializing.
            await self._db.refresh(row)
            response = metadata_response(row)
            # Final authority re-read after the last statement that can block.
            grant = await self.guard.check(**access)
            await _audit(
                self._db, event_type="network.campus_model_asset.uploaded", actor_id=actor_id, network_id=network_id,
                resource_type="campus_model_asset", resource_id=response.campus_model_asset_id,
                correlation_id=correlation_id, grant=grant, metadata={
                    "asset_id": str(response.campus_model_asset_id), "model_sha256": req.model_sha256,
                    "model_size_bytes": req.model_size_bytes, "replace_existing": req.replace_existing,
                    "reused_record": same_body, "retired_records": retired, "new_object": published,
                },
            )
            await self._db.commit()
            return CampusModelAssetListResponse(items=[response], total=1)
        except BaseException:
            await self._db.rollback()
            if published:
                await self._discard_orphan(req.model_sha256)
            raise

    async def _assert_network_quota(self, *, network_id: uuid.UUID, req: UpsertCampusModelAssetRequest,
                                    same_body: bool) -> None:
        """Per-network quota from DB accounting of ACTIVE assets (retirement frees it)."""
        settings = self._asset_store.settings
        used_bytes, used_count = await self._repo.active_usage(network_id)
        if req.replace_existing:
            after_bytes, after_count = req.model_size_bytes, 1
        elif same_body:
            after_bytes, after_count = used_bytes, used_count
        else:
            after_bytes, after_count = used_bytes + req.model_size_bytes, used_count + 1
        if after_bytes > settings.network_max_active_bytes or after_count > settings.network_max_active_assets:
            raise HTTPException(status_code=507, detail={
                "code": "CAMPUS_MODEL_ASSET_QUOTA_EXCEEDED",
                "message": "Network campus model asset quota exceeded; retire unused assets first.",
            })

    async def _discard_orphan(self, digest: str) -> None:
        """Remove a blob this request published if no asset row references it.

        Runs after the failed transaction rolled back, in a new transaction holding
        the digest lock, so a concurrent uploader of the same bytes is never harmed.
        Failures are logged; the offline collector removes any remaining orphan.
        """
        from app.modules.network.asset_io import storage_call

        try:
            await self._repo.lock_digest(digest)
            if not await self._repo.digest_referenced(digest):
                await storage_call(self._asset_store.remove_unreferenced, digest)
            await self._db.commit()
        except BaseException as exc:  # noqa: BLE001 - cleanup never masks the original failure
            logger.warning("campus_model_asset_orphan_cleanup_failed", error_type=type(exc).__name__)
            try:
                await self._db.rollback()
            except Exception:  # noqa: BLE001
                pass
            if not isinstance(exc, Exception):
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
                    status_code=422,
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
                status_code=422,
                detail={
                    "code": "CAMPUS_MODEL_ASSET_MAPPING_DEVICE_NOT_FOUND",
                    "message": (
                        "mapping_by_device_id references devices that are not active in this network: "
                        f"{preview}"
                    ),
                },
            )


def _group_conflict(group_key: str) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": "DEVICE_GROUP_CONFLICT",
        "message": f"Device group '{group_key}' changed since it was read; reload before saving.",
    })


class DeviceGroupService(_GuardedService):

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = DeviceGroupRepository(db)
        self._network_repo = NetworkRepository(db)
        self._device_repo = DeviceRepository(db)
        self._workspace_svc = workspace_service(db, redis)

    async def list_groups(
        self,
        *,
        network_id: uuid.UUID,
        actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> DeviceGroupListResponse:
        await self.guard.authorize(**self._access(
            network_id=network_id, actor_user_id=actor_user_id, requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id,
        ))
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
        correlation_id: str | None = None,
    ) -> DeviceGroupListResponse:
        """Create/update groups in place with C8 ``expected_updated_at`` checks.

        Only membership differences are written. ``replace_existing`` soft-deletes
        active groups absent from the request; kept groups retain their identity.
        """
        access = self._access(network_id=network_id, actor_user_id=actor_id, require_write=True,
                              requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        try:
            grant = await self.guard.authorize(**access, lock=LockPolicy.EXCLUSIVE)
            devices = await self._device_repo.list_active_for_network(network_id)
            devices_by_id = {device.device_id: device for device in devices}
            desired = {
                group.group_key: (group, self._resolve_group_device_ids(
                    group=group, network_id=network_id, devices=devices, devices_by_id=devices_by_id,
                ))
                for group in req.groups
            }
            existing = await self._repo.get_active_by_keys(network_id, list(desired))
            for key, (group, _) in desired.items():
                row = existing.get(key)
                if group.expected_updated_at is not None and (
                    row is None or row.updated_at != group.expected_updated_at
                ):
                    raise _group_conflict(key)
            current_members = await self._repo.list_members_for_group_ids(
                [row.device_group_id for row in existing.values()],
            )
            counts = {"created": 0, "updated": 0, "unchanged": 0, "members_added": 0, "members_removed": 0}
            group_ids: list[uuid.UUID] = []
            for key, (group, device_ids) in desired.items():
                values = {"name": group.name, "group_type": group.group_type,
                          "description": group.description, "selector": dict(group.selector)}
                row = existing.get(key)
                if row is None:
                    group_id = await self._repo.upsert_group(network_id=network_id, group_key=key, **values)
                    current = set((await self._repo.list_members_for_group_ids([group_id])).get(group_id, []))
                    counts["created"] += 1
                else:
                    group_id = row.device_group_id
                    current = set(current_members.get(group_id, []))
                desired_ids = set(device_ids)
                additions, removals = sorted(desired_ids - current), sorted(current - desired_ids)
                await self._repo.apply_member_diff(group_id, add=additions, remove=removals)
                counts["members_added"] += len(additions)
                counts["members_removed"] += len(removals)
                if row is not None:
                    changed = additions or removals or any(
                        getattr(row, field) != value for field, value in values.items()
                    )
                    if changed:
                        await self._repo.update_group(group_id, **values)
                        counts["updated"] += 1
                    else:
                        counts["unchanged"] += 1
                group_ids.append(group_id)
            retired = await self._repo.soft_delete_absent(network_id, list(desired)) if req.replace_existing else []
            # Reload rows so server-generated updated_at is real and never lazy-loaded.
            rows = await self._repo.get_groups_by_ids(group_ids)
            members_by_group_id = await self._repo.list_members_for_group_ids(group_ids)
            items = [self._to_group_response(rows[group_id], members_by_group_id.get(group_id, []))
                     for group_id in group_ids]
            await _audit(
                self._db, event_type="network.device_groups.upserted", actor_id=actor_id, network_id=network_id,
                resource_type="network_device_groups", resource_id=network_id, correlation_id=correlation_id,
                grant=grant, metadata={
                    "replace_existing": req.replace_existing, **counts, "retired": len(retired),
                    "group_keys": list(desired)[:_AUDIT_ID_PREVIEW],
                },
            )
            await self._db.commit()
            return DeviceGroupListResponse(items=items, total=len(items))
        except BaseException:
            await self._db.rollback()
            raise

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
                status_code=422,
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

            device_type = getattr(device, "device_type", None)
            # One classifier (device_types) normalizes and interprets every device type.
            if device_type_selector is not None and normalize_device_type(device_type) != device_type_selector:
                continue

            if functional_group is not None and not matches_functional_group(device_type, functional_group):
                continue

            if operational_group is not None:
                location_hint = getattr(device, "location_hint", None)
                normalized_location = location_hint.strip().lower() if isinstance(location_hint, str) else ""
                if operational_group not in normalized_location:
                    continue

            selected.add(device.device_id)

        return sorted(selected)
