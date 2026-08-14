"""NANFO Backend - Alerts API router (/api/v1/alerts/*)."""

from __future__ import annotations

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    get_current_user,
    get_db,
    get_redis,
    get_request_meta,
)
from app.core.responses import APIResponse, success_response
from app.db.postgres import AsyncSession
from app.modules.alert.schemas import AlertActionResponse, AlertListResponse
from app.modules.alert.service import AlertService

router = APIRouter(prefix="/api/v1/alerts", tags=["Alerts"])


@router.get("", response_model=APIResponse[AlertListResponse], status_code=status.HTTP_200_OK)
async def list_alerts(
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    severity: Annotated[str | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    correlation_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
):
    _ = claims
    started = time.monotonic()
    payload = await AlertService(db=db, redis=redis).list_alerts(
        status_filter=status_filter,
        severity_filter=severity,
        source_filter=source,
        correlation_id_filter=correlation_id,
        search_filter=search,
        limit=limit,
    )
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/{alert_id}/ack", response_model=APIResponse[AlertActionResponse], status_code=status.HTTP_200_OK)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    payload = await AlertService(db=db, redis=redis).acknowledge_alert(
        alert_id=alert_id,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
    )
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/{alert_id}/resolve", response_model=APIResponse[AlertActionResponse], status_code=status.HTTP_200_OK)
async def resolve_alert(
    alert_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    payload = await AlertService(db=db, redis=redis).resolve_alert(
        alert_id=alert_id,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
    )
    return success_response(payload, meta.request_id, started, meta.timestamp)
