"""NANFO Backend - Intent API router (/api/v1/intents/*)."""

from __future__ import annotations

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, status

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
from app.modules.intent.schemas import (
    ExecuteIntentRequest,
    ExecuteIntentResponse,
    IntentDetailResponse,
    ValidateIntentRequest,
    ValidateIntentResponse,
)
from app.modules.intent.service import IntentExecutionService, IntentValidationService
from app.modules.intent.history import IntentHistoryPage, IntentHistoryService
from app.modules.organization.service import WorkspaceService

router = APIRouter(prefix="/api/v1/intents", tags=["Intent"])


@router.post("/validate", response_model=APIResponse[ValidateIntentResponse], status_code=status.HTTP_200_OK)
async def validate_intent(
    req: ValidateIntentRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
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
    idempotency_key = None
    if hasattr(meta, "request") and meta.request is not None:
        idempotency_key = meta.request.headers.get("Idempotency-Key")
    result = await IntentValidationService(db=db, redis=redis).validate_intent(
        workspace_id=scoped_workspace_id,
        network_id=req.network_id,
        intent_payload=req.intent,
        idempotency_key=idempotency_key,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
    )
    payload = ValidateIntentResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/execute", response_model=APIResponse[ExecuteIntentResponse], status_code=status.HTTP_202_ACCEPTED)
async def execute_intent(
    req: ExecuteIntentRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
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
    effective_idempotency_key = req.idempotency_key or header_idempotency_key
    result = await IntentExecutionService(db=db, redis=redis).execute_intent(
        workspace_id=scoped_workspace_id,
        intent_id=req.intent_id,
        idempotency_key=effective_idempotency_key,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
        requested_permissions=claims.permissions,
        manual_approval=req.manual_approval,
        cancel=req.cancel,
        simulation_id=req.simulation_id,
    )
    payload = ExecuteIntentResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.get("", response_model=APIResponse[IntentHistoryPage])
async def list_intents(
    workspace_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    network_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    started = time.monotonic()
    workspace_id = enforce_workspace_scope(claims=claims, workspace_id=workspace_id)
    result = await IntentHistoryService(db=db, redis=redis).list_page(
        workspace_id=workspace_id, network_id=network_id, user_id=claims.user_id,
        claim_org_id=get_claim_org_scope(claims=claims), page=page, page_size=page_size,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{intent_id}", response_model=APIResponse[IntentDetailResponse], status_code=status.HTTP_200_OK)
async def get_intent(
    intent_id: uuid.UUID,
    workspace_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    scoped_workspace_id = enforce_workspace_scope(claims=claims, workspace_id=workspace_id)
    await WorkspaceService(db=db, redis=redis).get_active_workspace(
        scoped_workspace_id, user_id=claims.user_id, claim_org_id=get_claim_org_scope(claims=claims),
    )
    started = time.monotonic()
    result = await IntentExecutionService(db=db, redis=redis).get_intent_detail(
        workspace_id=scoped_workspace_id,
        intent_id=intent_id,
        user_id=claims.user_id,
    )
    payload = IntentDetailResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)
