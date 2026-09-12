"""Approved ADR-012 autonomy surfaces; no worker startup."""

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
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


@router.get("", response_model=APIResponse[AutonomyResponse])
async def get_autonomy(network_id: uuid.UUID, claims: Claims, meta: Meta, db: Database, redis: Redis,
                       history_limit: int = Query(default=20, ge=1, le=100)):
    started = time.monotonic()
    result = await AutonomyService(db, redis).get(claims=claims, network_id=network_id, history_limit=history_limit)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.put("", response_model=APIResponse[AutonomyResponse])
async def set_autonomy(request: SetAutonomyRequest, claims: Claims, meta: Meta, db: Database, redis: Redis):
    started = time.monotonic()
    result = await AutonomyService(db, redis).set_mode(claims=claims, request=request)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.post("/stop", response_model=APIResponse[AutonomyResponse], status_code=200)
async def stop_autonomy(request: StopAutonomyRequest, claims: Claims, meta: Meta, db: Database, redis: Redis):
    started = time.monotonic()
    result = await AutonomyService(db, redis).stop(claims=claims, network_id=request.network_id)
    return success_response(result, meta.request_id, started, meta.timestamp)
