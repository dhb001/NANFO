"""ADR-018 approved configuration/override routes; model diagnostics use a separate router."""

import time
import uuid

from fastapi import APIRouter

from app.api.v1.autonomy import Claims, Database, Meta, Redis
from app.core.responses import APIResponse, success_response
from app.modules.autonomy.configuration import ConfigurationService
from app.modules.autonomy.overrides import OverrideService
from app.modules.autonomy.schemas import (
    ConfigurationResponse,
    CreateOverrideRequest,
    OverrideListResponse,
    OverrideResponse,
    ReturnOverrideRequest,
    SetConfigurationRequest,
)

router = APIRouter(prefix="/api/v1/autonomy", tags=["Autonomy"])


@router.get("/configuration", response_model=APIResponse[ConfigurationResponse])
async def get_configuration(network_id: uuid.UUID, claims: Claims, meta: Meta, db: Database, redis: Redis):
    started = time.monotonic()
    result = await ConfigurationService(db, redis).get(claims=claims, network_id=network_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.put("/configuration", response_model=APIResponse[ConfigurationResponse])
async def put_configuration(request: SetConfigurationRequest, claims: Claims, meta: Meta, db: Database, redis: Redis):
    started = time.monotonic()
    result = await ConfigurationService(db, redis).put(claims=claims, request=request)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/overrides", response_model=APIResponse[OverrideListResponse])
async def get_overrides(network_id: uuid.UUID, claims: Claims, meta: Meta, db: Database, redis: Redis):
    started = time.monotonic()
    result = await OverrideService(db, redis).list(claims=claims, network_id=network_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.post("/overrides", response_model=APIResponse[OverrideResponse], status_code=201)
async def create_override(request: CreateOverrideRequest, claims: Claims, meta: Meta, db: Database, redis: Redis):
    started = time.monotonic()
    result = await OverrideService(db, redis).create(claims=claims, request=request)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.post("/overrides/{override_id}/cancel", response_model=APIResponse[OverrideResponse])
async def cancel_override(override_id: uuid.UUID, claims: Claims, meta: Meta, db: Database, redis: Redis):
    started = time.monotonic()
    result = await OverrideService(db, redis).cancel(claims=claims, override_id=override_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.post("/overrides/{override_id}/return", response_model=APIResponse[OverrideResponse])
async def return_override(override_id: uuid.UUID, request: ReturnOverrideRequest, claims: Claims, meta: Meta, db: Database, redis: Redis):
    started = time.monotonic()
    result = await OverrideService(db, redis).return_mode(claims=claims, override_id=override_id, request=request)
    return success_response(result, meta.request_id, started, meta.timestamp)
