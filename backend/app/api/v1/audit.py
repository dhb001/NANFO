"""NANFO Backend — Audit log API router (/api/v1/audit/*).

GET /api/v1/audit/logs — Admin-only (Q6 resolved: Admin role required).
Returns paginated audit log entries (Identity module, Authentication.md §4).
"""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    get_db,
    get_redis,
    get_request_meta,
    require_roles,
)
from app.core.responses import APIResponse, success_response
from app.modules.identity.repository import AuditLogRepository
from app.modules.identity.schemas import AuditLogEntry

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


@router.get("/logs", response_model=APIResponse[dict], status_code=status.HTTP_200_OK)
async def list_audit_logs(
    # Q6 answer: Admin role only (design_package §6 Q6)
    claims: Annotated[TokenClaims, Depends(require_roles("Admin"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    actor_id: uuid.UUID | None = Query(default=None),
    org_id: uuid.UUID | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
):
    started = time.monotonic()
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
