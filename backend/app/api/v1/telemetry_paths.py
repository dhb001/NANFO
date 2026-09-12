"""ADR018 selected-probe read composition. No capture/control endpoint."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
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
from app.modules.identity.service import AuthService
from app.modules.network.emulation import EmulationDiscoveryService, load_binding
from app.modules.network.repository import DeviceRepository
from app.modules.network.service import NetworkService
from app.modules.telemetry.emulation import SnapshotReader
from app.modules.telemetry.paths import ProbePathsReader, ProbePathsResponse

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry"])


async def read_paths(*, settings, db, redis, claims, network_id):
    network = await NetworkService(db, redis).assert_network_workspace_access(
        network_id=network_id, requested_workspace_id=get_claim_workspace_scope(claims=claims),
        actor_user_id=claims.user_id, claim_org_id=get_claim_org_scope(claims=claims),
    )
    result = ProbePathsResponse(network_id=network.network_id, workspace_id=network.workspace_id,
                                status="unavailable")
    if (settings.EXECUTION_MODE != "emulation" or not settings.EMULATION_SNAPSHOT_PATH
            or not settings.EMULATION_BINDING_PATH):
        return result.model_copy(update={"reason": "probe_provider_not_configured"})
    try:
        from emulation.topology import manifest
    except ImportError:
        return result.model_copy(update={"reason": "probe_provider_not_installed"})

    snapshot_path = Path(settings.EMULATION_SNAPSHOT_PATH)
    try:
        binding = await load_binding(Path(settings.EMULATION_BINDING_PATH), snapshot_path=snapshot_path)
        if binding.network_id != network.network_id or binding.workspace_id != network.workspace_id:
            return result.model_copy(update={"reason": "binding_scope_mismatch"})
        # Current owner capabilities, writable membership and active device ownership;
        # validation only, never the discovery service's graph-mutating apply_snapshot.
        await EmulationDiscoveryService(
            identity=AuthService(db, redis), network=NetworkService(db, redis),
            devices=DeviceRepository(db), topology=None, expected_topology=manifest(),
        ).validate_binding(binding)
    except (OSError, ValueError, HTTPException):
        return result.model_copy(update={"reason": "trusted_binding_unavailable"})
    return await ProbePathsReader(SnapshotReader(
        snapshot_path, max_bytes=settings.EMULATION_SNAPSHOT_MAX_BYTES,
        max_age_seconds=settings.EMULATION_SNAPSHOT_MAX_AGE_SECONDS,
        future_skew_seconds=settings.EMULATION_SNAPSHOT_FUTURE_SKEW_SECONDS,
    )).read(binding=binding, network_id=network.network_id, workspace_id=network.workspace_id)


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
