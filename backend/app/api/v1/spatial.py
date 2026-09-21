"""ADR-021 canonical Network-owned spatial scenes."""

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Path, Query
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
from app.modules.network.spatial_schemas import (
    MAX_REVISION,
    ReplaceSpatialSceneRequest,
    SpatialHistoryList,
    SpatialSceneDocument,
)
from app.modules.network.spatial_service import SpatialSceneService

router = APIRouter(prefix="/api/v1/networks", tags=["Spatial scene"])


@router.get("/{network_id}/spatial-scene", response_model=APIResponse[SpatialSceneDocument])
async def get_spatial_scene(
    network_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    result = await SpatialSceneService(db=db, redis=redis).get_scene(
        network_id=network_id, actor_user_id=claims.user_id,
        requested_workspace_id=enforce_workspace_scope(claims=claims, workspace_id=None),
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{network_id}/spatial-scene/history", response_model=APIResponse[SpatialHistoryList])
async def list_spatial_history(
    network_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    started = time.monotonic()
    result = await SpatialSceneService(db=db, redis=redis).list_history(
        network_id=network_id, actor_user_id=claims.user_id, page=page, page_size=page_size,
        requested_workspace_id=enforce_workspace_scope(claims=claims, workspace_id=None),
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{network_id}/spatial-scene/history/{revision}", response_model=APIResponse[SpatialSceneDocument])
async def get_spatial_revision(
    network_id: uuid.UUID,
    revision: Annotated[int, Path(ge=0, le=MAX_REVISION)],
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    result = await SpatialSceneService(db=db, redis=redis).get_revision(
        network_id=network_id, revision=revision, actor_user_id=claims.user_id,
        requested_workspace_id=enforce_workspace_scope(claims=claims, workspace_id=None),
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.put("/{network_id}/spatial-scene", response_model=APIResponse[SpatialSceneDocument])
async def replace_spatial_scene(
    network_id: uuid.UUID,
    req: ReplaceSpatialSceneRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    result = await SpatialSceneService(db=db, redis=redis).replace_scene(
        network_id=network_id, req=req, actor_user_id=claims.user_id, correlation_id=meta.request_id,
        requested_workspace_id=enforce_workspace_scope(claims=claims, workspace_id=None),
        claim_org_id=get_claim_org_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)
