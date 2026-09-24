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
    get_claim_org_scope,
    get_claim_workspace_scope,
    get_db,
    get_redis,
    get_request_meta,
    require_permissions,
)
from app.core.responses import APIResponse, success_response
from app.db.postgres import AsyncSession
from app.modules.alert.repository import MAX_SEARCH_LENGTH
from app.modules.alert.schemas import AlertActionResponse, AlertHistoryResponse, AlertListResponse, AlertRecordResponse
from app.modules.alert.service import AlertService

router = APIRouter(prefix="/api/v1/alerts", tags=["Alerts"])
# Global (platform) role that may read platform-scoped alerts, as for audit scope=platform (C7).
PLATFORM_ALERT_ROLE = "Admin"


def platform_reader(claims: TokenClaims, *, claim_org_id: uuid.UUID | None,
                    claim_workspace_id: uuid.UUID | None) -> bool:
    """Global Admin with an unscoped token: may list/read platform-scoped alerts.

    Roles are reloaded from Identity on every request (never the signed snapshot);
    an org- or workspace-scoped token is a tenant view and never sees them.
    """
    return PLATFORM_ALERT_ROLE in claims.roles and claim_org_id is None and claim_workspace_id is None


@router.get("/{alert_id}", response_model=APIResponse[AlertRecordResponse])
async def get_alert(
    alert_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:telemetry"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    workspace_claim, org_claim = get_claim_workspace_scope(claims=claims), get_claim_org_scope(claims=claims)
    payload = await AlertService(db=db, redis=redis).get_alert(alert_id=alert_id,
        actor_user_id=claims.user_id, requested_workspace_id=workspace_claim, claim_org_id=org_claim,
        platform_reader=platform_reader(claims, claim_org_id=org_claim, claim_workspace_id=workspace_claim))
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.get("/{alert_id}/history", response_model=APIResponse[AlertHistoryResponse])
async def get_alert_history(
    alert_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:telemetry"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    workspace_claim, org_claim = get_claim_workspace_scope(claims=claims), get_claim_org_scope(claims=claims)
    payload = await AlertService(db=db, redis=redis).get_history(alert_id=alert_id,
        actor_user_id=claims.user_id, requested_workspace_id=workspace_claim, claim_org_id=org_claim,
        platform_reader=platform_reader(claims, claim_org_id=org_claim, claim_workspace_id=workspace_claim))
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.get("", response_model=APIResponse[AlertListResponse], status_code=status.HTTP_200_OK)
async def list_alerts(
    claims: Annotated[TokenClaims, Depends(require_permissions("read:telemetry"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    severity: Annotated[str | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    correlation_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=MAX_SEARCH_LENGTH)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    workspace_id: Annotated[uuid.UUID | None, Query()] = None,
    network_id: Annotated[uuid.UUID | None, Query()] = None,
):
    started = time.monotonic()
    requested_workspace_id = get_claim_workspace_scope(claims=claims)
    claim_org_id = get_claim_org_scope(claims=claims)
    payload = await AlertService(db=db, redis=redis).list_alerts(
        status_filter=status_filter,
        severity_filter=severity,
        source_filter=source,
        correlation_id_filter=correlation_id,
        search_filter=search,
        limit=limit,
        actor_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=claim_org_id,
        workspace_id_filter=workspace_id,
        network_id_filter=network_id,
        platform_reader=platform_reader(claims, claim_org_id=claim_org_id,
                                        claim_workspace_id=requested_workspace_id),
    )
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/{alert_id}/ack", response_model=APIResponse[AlertActionResponse], status_code=status.HTTP_200_OK)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = get_claim_workspace_scope(claims=claims)
    claim_org_id = get_claim_org_scope(claims=claims)
    payload = await AlertService(db=db, redis=redis).acknowledge_alert(
        alert_id=alert_id,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=claim_org_id,
    )
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/{alert_id}/resolve", response_model=APIResponse[AlertActionResponse], status_code=status.HTTP_200_OK)
async def resolve_alert(
    alert_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = get_claim_workspace_scope(claims=claims)
    claim_org_id = get_claim_org_scope(claims=claims)
    payload = await AlertService(db=db, redis=redis).resolve_alert(
        alert_id=alert_id,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=claim_org_id,
    )
    return success_response(payload, meta.request_id, started, meta.timestamp)
