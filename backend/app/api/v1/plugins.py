"""NANFO Backend - Plugins API router (/api/v1/plugins/*)."""

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
    require_permissions,
)
from app.core.responses import APIResponse, success_response
from app.db.postgres import AsyncSession
from app.modules.plugin.schemas import (
    PluginActionResponse,
    PluginInstallRequest,
    PluginListResponse,
)
from app.modules.plugin.service import PluginService

router = APIRouter(prefix="/api/v1/plugins", tags=["Plugins"])


@router.get("", response_model=APIResponse[PluginListResponse], status_code=status.HTTP_200_OK)
async def list_plugins(
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    enabled: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
):
    started = time.monotonic()
    payload = await PluginService(db=db, redis=redis).list_plugins(
        status_filter=status_filter,
        enabled_filter=enabled,
        search_filter=search,
        limit=limit,
    )
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/install", response_model=APIResponse[PluginActionResponse], status_code=status.HTTP_201_CREATED)
async def install_plugin(
    req: PluginInstallRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    payload = await PluginService(db=db, redis=redis).install_plugin(
        req=req,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
    )
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/{plugin_id}/enable", response_model=APIResponse[PluginActionResponse], status_code=status.HTTP_200_OK)
async def enable_plugin(
    plugin_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    payload = await PluginService(db=db, redis=redis).enable_plugin(
        plugin_id=plugin_id,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
    )
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/{plugin_id}/disable", response_model=APIResponse[PluginActionResponse], status_code=status.HTTP_200_OK)
async def disable_plugin(
    plugin_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    payload = await PluginService(db=db, redis=redis).disable_plugin(
        plugin_id=plugin_id,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
    )
    return success_response(payload, meta.request_id, started, meta.timestamp)
