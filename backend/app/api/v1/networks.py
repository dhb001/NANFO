"""NANFO Backend — Networks API router (/api/v1/networks/*).

Implements network and device endpoints from design_package §4.3.
workspace_id validated via Organization module (C5).
Deferred topology endpoints excluded (C6).
"""

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    enforce_workspace_scope,
    get_claim_org_scope,
    get_db,
    get_redis,
    get_request_meta,
    require_permissions,
)
from app.core.responses import APIResponse, success_response
from app.modules.network.schemas import (
    CampusBuildingListResponse,
    CampusModelAssetListResponse,
    CreateDeviceRequest,
    CreateNetworkRequest,
    DeviceGroupListResponse,
    DeviceListResponse,
    DeviceResponse,
    NetworkListResponse,
    NetworkResponse,
    UpdateDeviceRequest,
    UpsertCampusBuildingsRequest,
    UpsertCampusModelAssetRequest,
    UpsertDeviceGroupsRequest,
)
from app.modules.network.service import (
    CampusBuildingService,
    CampusModelAssetService,
    DeviceGroupService,
    DeviceService,
    NetworkService,
)

router = APIRouter(prefix="/api/v1/networks", tags=["Networks"])


# ── Networks ──────────────────────────────────────────────────────────────────

@router.post("", response_model=APIResponse[NetworkResponse], status_code=status.HTTP_201_CREATED)
async def create_network(
    req: CreateNetworkRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    scoped_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=req.workspace_id)
    svc = NetworkService(db=db, redis=redis)
    result = await svc.create_network(
        req=req,
        actor_id=claims.user_id,
        correlation_id=meta.request_id,
        requested_workspace_id=scoped_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("", response_model=APIResponse[NetworkListResponse], status_code=status.HTTP_200_OK)
async def list_networks(
    workspace_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    page: int = 1,
    page_size: int = 20,
):
    started = time.monotonic()
    scoped_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=workspace_id)
    svc = NetworkService(db=db, redis=redis)
    result = await svc.list_networks(
        workspace_id=workspace_id,
        actor_user_id=claims.user_id,
        page=page,
        page_size=page_size,
        requested_workspace_id=scoped_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


# ── Devices ───────────────────────────────────────────────────────────────────

@router.post("/{network_id}/devices", response_model=APIResponse[DeviceResponse], status_code=status.HTTP_201_CREATED)
async def add_device(
    network_id: uuid.UUID,
    req: CreateDeviceRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=None)
    svc = DeviceService(db=db, redis=redis)
    result = await svc.add_device(
        network_id=network_id,
        req=req,
        actor_id=claims.user_id,
        correlation_id=meta.request_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{network_id}/devices", response_model=APIResponse[DeviceListResponse], status_code=status.HTTP_200_OK)
async def list_devices(
    network_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    page: int = 1,
    page_size: int = 20,
):
    started = time.monotonic()
    requested_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=None)
    svc = DeviceService(db=db, redis=redis)
    result = await svc.list_devices(
        network_id=network_id,
        actor_user_id=claims.user_id,
        page=page,
        page_size=page_size,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.patch("/{network_id}/devices/{device_id}", response_model=APIResponse[DeviceResponse], status_code=status.HTTP_200_OK)
async def update_device(
    network_id: uuid.UUID,
    device_id: uuid.UUID,
    req: UpdateDeviceRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=None)
    svc = DeviceService(db=db, redis=redis)
    result = await svc.update_device_spatial_ref(
        network_id=network_id,
        device_id=device_id,
        req=req,
        actor_id=claims.user_id,
        correlation_id=meta.request_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


# ── Campus Building Persistence (Phase 5D+) ──────────────────────────────────

@router.get(
    "/{network_id}/campus/buildings",
    response_model=APIResponse[CampusBuildingListResponse],
    status_code=status.HTTP_200_OK,
)
async def list_campus_buildings(
    network_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=None)
    result = await CampusBuildingService(db=db, redis=redis).list_buildings(
        network_id=network_id,
        actor_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.post(
    "/{network_id}/campus/buildings",
    response_model=APIResponse[CampusBuildingListResponse],
    status_code=status.HTTP_200_OK,
)
async def upsert_campus_buildings(
    network_id: uuid.UUID,
    req: UpsertCampusBuildingsRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=None)
    result = await CampusBuildingService(db=db, redis=redis).upsert_buildings(
        network_id=network_id,
        req=req,
        actor_id=claims.user_id,
        correlation_id=meta.request_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


# ── Campus Model Asset Persistence (Digital Twin residual closure) ────────────

@router.get(
    "/{network_id}/campus/model-assets",
    response_model=APIResponse[CampusModelAssetListResponse],
    status_code=status.HTTP_200_OK,
)
async def list_campus_model_assets(
    network_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=None)
    result = await CampusModelAssetService(db=db, redis=redis).list_assets(
        network_id=network_id,
        actor_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.post(
    "/{network_id}/campus/model-assets",
    response_model=APIResponse[CampusModelAssetListResponse],
    status_code=status.HTTP_200_OK,
)
async def upsert_campus_model_assets(
    network_id: uuid.UUID,
    req: UpsertCampusModelAssetRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=None)
    result = await CampusModelAssetService(db=db, redis=redis).upsert_asset(
        network_id=network_id,
        req=req,
        actor_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


# ── Device Groups (Digital Twin + intent targeting) ───────────────────────────

@router.get(
    "/{network_id}/device-groups",
    response_model=APIResponse[DeviceGroupListResponse],
    status_code=status.HTTP_200_OK,
)
async def list_device_groups(
    network_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=None)
    result = await DeviceGroupService(db=db, redis=redis).list_groups(
        network_id=network_id,
        actor_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.post(
    "/{network_id}/device-groups",
    response_model=APIResponse[DeviceGroupListResponse],
    status_code=status.HTTP_200_OK,
)
async def upsert_device_groups(
    network_id: uuid.UUID,
    req: UpsertDeviceGroupsRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=None)
    result = await DeviceGroupService(db=db, redis=redis).upsert_groups(
        network_id=network_id,
        req=req,
        actor_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)
