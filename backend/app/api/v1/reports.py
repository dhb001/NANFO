"""NANFO Backend - Reports API router (/api/v1/reports/*)."""

from __future__ import annotations

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status

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
from app.db.postgres import AsyncSession
from app.modules.organization.service import WorkspaceService
from app.modules.report.schemas import (
    GenerateReportRequest,
    ReportGenerateResponse,
    ReportRecordResponse,
)
from app.modules.report.service import ReportService

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


@router.post(
    "/generate",
    response_model=APIResponse[ReportGenerateResponse],
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions("write:config"))],
)
async def generate_report(
    req: GenerateReportRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:telemetry"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    scoped_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=req.workspace_id)
    await WorkspaceService(db=db, redis=redis).get_active_workspace(
        scoped_workspace_id, user_id=claims.user_id, claim_org_id=get_claim_org_scope(claims=claims),
        require_write=True,
    )
    header_idempotency_key = None
    if hasattr(meta, "request") and meta.request is not None:
        header_idempotency_key = meta.request.headers.get("Idempotency-Key")

    result = await ReportService(db=db, redis=redis).generate_report(
        workspace_id=scoped_workspace_id,
        network_id=req.network_id,
        report_type=req.report_type,
        output_format=req.format,
        date_range=req.date_range.model_dump(),
        scope=req.scope,
        filters=req.filters,
        fail_generation=False,
        idempotency_key=header_idempotency_key,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
    )
    payload = ReportGenerateResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.get(
    "/{report_id}",
    response_model=APIResponse[ReportRecordResponse],
    status_code=status.HTTP_200_OK,
)
async def get_report(
    report_id: uuid.UUID,
    workspace_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:telemetry"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    scoped_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=workspace_id)
    await WorkspaceService(db=db, redis=redis).get_active_workspace(
        scoped_workspace_id, user_id=claims.user_id, claim_org_id=get_claim_org_scope(claims=claims),
    )
    started = time.monotonic()
    result = await ReportService(db=db, redis=redis).get_report(
        report_id=report_id,
        workspace_id=scoped_workspace_id,
        user_id=claims.user_id,
    )
    payload = ReportRecordResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)
