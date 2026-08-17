"""NANFO Backend — Telemetry API router (/api/v1/telemetry/*)."""

from __future__ import annotations

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    enforce_workspace_scope,
    get_current_user,
    get_db,
    get_redis,
    get_request_meta,
    require_permissions,
)
from app.core.responses import APIResponse, success_response
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.schemas import (
    TelemetryDeviceHistoryResponse,
    TelemetryHealthResponse,
    TelemetryHistoryResponse,
)
from app.modules.telemetry.service import TelemetryQueryService

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry"])


@router.get("/history", response_model=APIResponse[TelemetryHistoryResponse], status_code=status.HTTP_200_OK)
async def get_telemetry_history(
    claims: Annotated[TokenClaims, Depends(require_permissions("read:telemetry"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    network_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    metric: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    started = time.monotonic()
    scoped_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=workspace_id)
    svc = TelemetryQueryService(db=db)
    result = await svc.get_history(
        network_id=network_id,
        workspace_id=scoped_workspace_id,
        metric=metric,
        page=page,
        page_size=page_size,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/device/{device_id}", response_model=APIResponse[TelemetryDeviceHistoryResponse], status_code=status.HTTP_200_OK)
async def get_device_telemetry(
    device_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:telemetry"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    metric: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    started = time.monotonic()
    svc = TelemetryQueryService(db=db)
    result = await svc.get_device_history(
        device_id=device_id,
        metric=metric,
        page=page,
        page_size=page_size,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/health", response_model=APIResponse[TelemetryHealthResponse], status_code=status.HTTP_200_OK)
async def get_telemetry_health(
    claims: Annotated[TokenClaims, Depends(require_permissions("read:telemetry"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    counter_service = TelemetryHealthCounterService(redis)
    svc = TelemetryQueryService(db=db, counter_service=counter_service, event_redis=redis)
    result = await svc.get_health()
    return success_response(result, meta.request_id, started, meta.timestamp)
