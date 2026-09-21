"""ADR018 separate router, deliberately independent of autonomy configuration."""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import RequestMeta, TokenClaims, get_current_user, get_db, get_redis, get_request_meta
from app.core.responses import APIResponse, success_response
from app.modules.autonomy.model_diagnostic_schemas import DiagnoseModelRequest, ModelDiagnosticRecord, ModelDiagnosticsResponse
from app.modules.autonomy.model_diagnostics import ModelDiagnosticsService

router = APIRouter(prefix="/api/v1/autonomy/model", tags=["Model Diagnostics"])
Claims = Annotated[TokenClaims, Depends(get_current_user)]
Meta = Annotated[RequestMeta, Depends(get_request_meta)]
Database = Annotated[AsyncSession, Depends(get_db)]
Redis = Annotated[object, Depends(get_redis)]


@router.get("", response_model=APIResponse[ModelDiagnosticsResponse])
async def get_model(network_id: uuid.UUID, claims: Claims, meta: Meta, db: Database, redis: Redis,
                    history_limit: int = Query(default=20, ge=1, le=100)):
    started = time.monotonic()
    result = await ModelDiagnosticsService(db, redis).get(claims, network_id, history_limit)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.post("/diagnose", response_model=APIResponse[ModelDiagnosticRecord], status_code=201)
async def diagnose_model(request: DiagnoseModelRequest, claims: Claims, meta: Meta, db: Database, redis: Redis):
    started = time.monotonic()
    result = await ModelDiagnosticsService(db, redis).diagnose(claims, request)
    return success_response(result, meta.request_id, started, meta.timestamp)
