"""Approved ADR-012 autonomy surfaces; no worker startup."""

import time
import uuid
from datetime import datetime
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    get_current_user,
    get_db,
    get_redis,
    get_request_meta,
)
from app.core.responses import APIResponse, ResponseMeta, success_response
from app.modules.autonomy.schemas import (
    AutonomyResponse,
    SetAutonomyRequest,
    StopAutonomyRequest,
)
from app.modules.autonomy.service import AutonomyService

router = APIRouter(prefix="/api/v1/autonomy", tags=["Autonomy"])
Claims = Annotated[TokenClaims, Depends(get_current_user)]
Meta = Annotated[RequestMeta, Depends(get_request_meta)]
Database = Annotated[AsyncSession, Depends(get_db)]
Redis = Annotated[aioredis.Redis, Depends(get_redis)]


class AutonomyModeMeta(ResponseMeta):
    """Additive C25 meta: true when the PUT was recorded for a second approver, not applied."""

    pending_approval: bool = False
    pending_approval_expires_at: datetime | None = None
    pending_requested_by_user_id: str | None = None


class AutonomyModeResponse(APIResponse[AutonomyResponse]):
    meta: AutonomyModeMeta


@router.get("", response_model=APIResponse[AutonomyResponse])
async def get_autonomy(network_id: uuid.UUID, claims: Claims, meta: Meta, db: Database, redis: Redis,
                       history_limit: int = Query(default=20, ge=1, le=100)):
    started = time.monotonic()
    result = await AutonomyService(db, redis).get(claims=claims, network_id=network_id, history_limit=history_limit)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.put("", response_model=AutonomyModeResponse, responses={202: {"model": AutonomyModeResponse}})
async def set_autonomy(request: SetAutonomyRequest, claims: Claims, meta: Meta, db: Database, redis: Redis,
                       response: Response):
    started = time.monotonic()
    service = AutonomyService(db, redis)
    result = await service.set_mode(claims=claims, request=request, correlation_id=meta.request_id)
    envelope = success_response(result, meta.request_id, started, meta.timestamp)
    pending = service.recorded_pending_approval
    if pending is not None:
        response.status_code = 202
    return AutonomyModeResponse(success=True, data=result, errors=None, meta=AutonomyModeMeta(
        **envelope.meta.model_dump(), pending_approval=pending is not None,
        pending_approval_expires_at=pending.expires_at if pending else None,
        pending_requested_by_user_id=pending.requested_by_user_id if pending else None))


@router.post("/stop", response_model=APIResponse[AutonomyResponse], status_code=200)
async def stop_autonomy(request: StopAutonomyRequest, claims: Claims, meta: Meta, db: Database, redis: Redis):
    started = time.monotonic()
    result = await AutonomyService(db, redis).stop(claims=claims, network_id=request.network_id,
                                                   correlation_id=meta.request_id)
    return success_response(result, meta.request_id, started, meta.timestamp)
