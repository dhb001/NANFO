"""ADR018 selected-probe read route. No capture/control endpoint.

Composition (owner access check, binding validation, pcap replay) lives in the
Telemetry-owned ``ProbePathsService``; the router only maps claims and envelopes.
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
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
from app.modules.telemetry.paths import ProbePathsResponse
from app.modules.telemetry.probe_paths import ProbePathsService

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry"])


async def read_paths(*, settings, db, redis, claims, network_id) -> ProbePathsResponse:
    return await ProbePathsService(db=db, redis=redis, settings=settings).read(
        network_id=network_id, actor_user_id=claims.user_id,
        requested_workspace_id=get_claim_workspace_scope(claims=claims),
        claim_org_id=get_claim_org_scope(claims=claims),
    )


@router.get("/paths", response_model=APIResponse[ProbePathsResponse])
async def get_paths(
    network_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:telemetry"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    result = await read_paths(settings=get_settings(), db=db, redis=redis,
                              claims=claims, network_id=network_id)
    return success_response(result, meta.request_id, started, meta.timestamp)
