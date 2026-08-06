"""NANFO Backend — Networks API router (/api/v1/networks/*).

Implements network and device endpoints from design_package §4.3.
workspace_id validated via Organization module (C5).
Deferred topology endpoints excluded (C6).
"""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    get_current_user,
    get_db,
    get_redis,
    get_request_meta,
)
from app.core.responses import APIResponse, success_response
from app.modules.network.schemas import (
    CreateDeviceRequest,
    CreateNetworkRequest,
    DeviceListResponse,
    DeviceResponse,
    NetworkListResponse,
    NetworkResponse,
)
from app.modules.network.service import DeviceService, NetworkService

router = APIRouter(prefix="/api/v1/networks", tags=["Networks"])


# ── Networks ──────────────────────────────────────────────────────────────────

@router.post("", response_model=APIResponse[NetworkResponse], status_code=status.HTTP_201_CREATED)
async def create_network(
    req: CreateNetworkRequest,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
):
    started = time.monotonic()
    svc = NetworkService(db=db, redis=redis)
    result = await svc.create_network(req=req, actor_id=claims.user_id, correlation_id=meta.request_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("", response_model=APIResponse[NetworkListResponse], status_code=status.HTTP_200_OK)
async def list_networks(
    workspace_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
    page: int = 1,
    page_size: int = 20,
):
    started = time.monotonic()
    svc = NetworkService(db=db, redis=redis)
    result = await svc.list_networks(workspace_id=workspace_id, page=page, page_size=page_size)
    return success_response(result, meta.request_id, started, meta.timestamp)


# ── Devices ───────────────────────────────────────────────────────────────────

@router.post("/{network_id}/devices", response_model=APIResponse[DeviceResponse], status_code=status.HTTP_201_CREATED)
async def add_device(
    network_id: uuid.UUID,
    req: CreateDeviceRequest,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
):
    started = time.monotonic()
    svc = DeviceService(db=db, redis=redis)
    result = await svc.add_device(network_id=network_id, req=req, actor_id=claims.user_id, correlation_id=meta.request_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{network_id}/devices", response_model=APIResponse[DeviceListResponse], status_code=status.HTTP_200_OK)
async def list_devices(
    network_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
    page: int = 1,
    page_size: int = 20,
):
    started = time.monotonic()
    svc = DeviceService(db=db, redis=redis)
    result = await svc.list_devices(network_id=network_id, page=page, page_size=page_size)
    return success_response(result, meta.request_id, started, meta.timestamp)
