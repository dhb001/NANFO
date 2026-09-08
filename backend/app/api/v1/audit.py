"""NANFO Backend — Audit log API router (/api/v1/audit/*).

GET /api/v1/audit/logs — Admin-only (Q6 resolved: Admin role required).
Returns paginated audit log entries (Identity module, Authentication.md §4).
"""

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    enforce_org_scope,
    get_claim_org_scope,
    get_claim_workspace_scope,
    get_db,
    get_redis,
    get_request_meta,
    require_roles,
)
from app.core.responses import APIResponse, success_response
from app.modules.identity.repository import AuditLogRepository
from app.modules.identity.schemas import AuditLogEntry
from app.modules.organization.service import OrgService, WorkspaceService

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


@router.get("/logs", response_model=APIResponse[dict], status_code=status.HTTP_200_OK)
async def list_audit_logs(
    # Q6 answer: Admin role only (design_package §6 Q6)
    claims: Annotated[TokenClaims, Depends(require_roles("Admin"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    org_id: Annotated[uuid.UUID | None, Query()] = None,
    resource_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
):
    started = time.monotonic()
    org_id = org_id or get_claim_org_scope(claims=claims)
    if org_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
    enforce_org_scope(claims=claims, org_id=org_id)
    await OrgService(db=db, redis=redis).get_org(org_id=org_id, user_id=claims.user_id)
    workspace_id = get_claim_workspace_scope(claims=claims)
    if workspace_id is not None:
        await WorkspaceService(db=db, redis=redis).get_active_workspace(
            workspace_id, user_id=claims.user_id, claim_org_id=org_id,
        )
    repo = AuditLogRepository(db)
    entries, total = await repo.list_entries(
        actor_id=actor_id,
        org_id=org_id,
        resource_type=resource_type,
        page=page,
        page_size=page_size,
    )
    data = {
        "items": [
            AuditLogEntry(
                log_id=e.log_id,
                event_type=e.event_type,
                actor_id=e.actor_id,
                resource_type=e.resource_type,
                resource_id=e.resource_id,
                org_id=e.org_id,
                correlation_id=e.correlation_id,
                timestamp=e.timestamp,
                metadata=e.metadata_,
            ).model_dump()
            for e in entries
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
    return success_response(data, meta.request_id, started, meta.timestamp)
