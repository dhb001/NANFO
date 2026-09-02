"""NANFO Backend — Telemetry API router (/api/v1/telemetry/*)."""

from __future__ import annotations

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    enforce_workspace_scope,
    get_claim_org_scope,
    get_claim_workspace_scope,
    get_db,
    get_redis,
    get_request_meta,
    require_permissions,
)
from app.core.responses import APIResponse, success_response
from app.modules.network.service import NetworkService
from app.modules.organization.service import WorkspaceService
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.schemas import (
    TelemetryDeviceHistoryResponse,
    TelemetryHealthResponse,
    TelemetryHistoryResponse,
)
from app.modules.telemetry.service import TelemetryQueryService

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry"])


async def _resolve_history_scope(
    *,
    claims: TokenClaims,
    db: AsyncSession,
    redis: aioredis.Redis,
    network_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None,
) -> tuple[uuid.UUID | None, uuid.UUID]:
    """Resolve and enforce telemetry history tenant scope.

    History queries must always resolve to a single workspace scope through either:
    - `network_id` ownership resolution, or
    - explicit/request-bound `workspace_id` scope.
    """
    scoped_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=workspace_id)
    claim_org_id = get_claim_org_scope(claims=claims)

    if network_id is not None:
        network = await NetworkService(db=db, redis=redis).assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=scoped_workspace_id,
            actor_user_id=claims.user_id,
            claim_org_id=claim_org_id,
        )
        return network.network_id, network.workspace_id

    if scoped_workspace_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

    await WorkspaceService(db=db, redis=redis).get_active_workspace(
        scoped_workspace_id,
        user_id=claims.user_id,
        claim_org_id=claim_org_id,
    )
    return None, scoped_workspace_id


async def _resolve_device_scope(
    *,
    claims: TokenClaims,
    db: AsyncSession,
    redis: aioredis.Redis,
    device_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID]:
    return await NetworkService(db=db, redis=redis).assert_device_workspace_access(
        device_id=device_id,
        requested_workspace_id=get_claim_workspace_scope(claims=claims),
        actor_user_id=claims.user_id,
        claim_org_id=get_claim_org_scope(claims=claims),
    )


async def _enforce_health_scope(
    *,
    claims: TokenClaims,
    db: AsyncSession,
    redis: aioredis.Redis,
) -> None:
    """Validate optional claim scope semantics for telemetry health reads.

    Policy: telemetry health remains an operational endpoint, but optional
    `workspace_id` / `org_id` claims must still resolve to valid membership scope.
    """
    claim_workspace_id = get_claim_workspace_scope(claims=claims)
    claim_org_id = get_claim_org_scope(claims=claims)
    workspace_svc = WorkspaceService(db=db, redis=redis)

    if claim_workspace_id is not None:
        await workspace_svc.get_active_workspace(
            claim_workspace_id,
            user_id=claims.user_id,
            claim_org_id=claim_org_id,
        )
        return

    if claim_org_id is not None:
        await workspace_svc.list_workspaces(
            org_id=claim_org_id,
            user_id=claims.user_id,
            page=1,
            page_size=1,
        )


@router.get("/history", response_model=APIResponse[TelemetryHistoryResponse], status_code=status.HTTP_200_OK)
async def get_telemetry_history(
    claims: Annotated[TokenClaims, Depends(require_permissions("read:telemetry"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    network_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    metric: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    started = time.monotonic()
    scoped_network_id, scoped_workspace_id = await _resolve_history_scope(
        claims=claims,
        db=db,
        redis=redis,
        network_id=network_id,
        workspace_id=workspace_id,
    )
    svc = TelemetryQueryService(db=db)
    result = await svc.get_history(
        network_id=scoped_network_id,
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
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    metric: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    started = time.monotonic()
    network_id, workspace_id = await _resolve_device_scope(
        claims=claims,
        db=db,
        redis=redis,
        device_id=device_id,
    )
    svc = TelemetryQueryService(db=db)
    result = await svc.get_device_history(
        device_id=device_id,
        network_id=network_id,
        workspace_id=workspace_id,
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
    await _enforce_health_scope(claims=claims, db=db, redis=redis)
    counter_service = TelemetryHealthCounterService(redis)
    svc = TelemetryQueryService(db=db, counter_service=counter_service, event_redis=redis)
    result = await svc.get_health()
    return success_response(result, meta.request_id, started, meta.timestamp)
