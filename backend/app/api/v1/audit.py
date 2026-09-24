"""NANFO Backend — Audit log API router (/api/v1/audit/*).

GET /api/v1/audit/logs — global Admin only (Q6 resolved: Admin role required).
Returns paginated audit log entries through Identity's AuditQueryService
(Authentication.md §4/§9, ADR-028 C7).

Scopes:
  * ``scope=org`` (default): one organization's events. Requires ``org_id`` (or
    an org-scoped token) and current membership of that organization.
  * ``scope=platform``: unscoped (``org_id IS NULL``) platform events such as
    authentication. Global Admin with an unscoped token only.

Optional token claims only narrow access. Audit rows carry no workspace
attribution, so a workspace-scoped token cannot be narrowed to its workspace
and is denied rather than shown the whole organization.
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
from app.core.pagination import PageNumber
from app.core.responses import APIResponse, success_response
from app.modules.identity.audit import AuditQueryService
from app.modules.identity.schemas import AuditLogPage, AuditScope
from app.modules.organization.service import OrgService

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")


@router.get("/logs", response_model=APIResponse[AuditLogPage], status_code=status.HTTP_200_OK)
async def list_audit_logs(
    # Q6 answer: Admin role only (design_package §6 Q6)
    claims: Annotated[TokenClaims, Depends(require_roles("Admin"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    org_id: Annotated[uuid.UUID | None, Query()] = None,
    resource_type: str | None = Query(default=None, max_length=100),
    page: PageNumber = 1,
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=200),
    scope: AuditScope = Query(default="org"),
):
    started = time.monotonic()
    claim_org_id = get_claim_org_scope(claims=claims)
    if get_claim_workspace_scope(claims=claims) is not None:
        raise _forbidden()

    if scope == "platform":
        if claim_org_id is not None:
            raise _forbidden()
        if org_id is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                                detail="org_id cannot be combined with scope=platform.")
    else:
        org_id = org_id or claim_org_id
        if org_id is None:
            raise _forbidden()
        enforce_org_scope(claims=claims, org_id=org_id)
        # Absent, deleted and foreign organizations are indistinguishable here (403).
        await OrgService(db=db, redis=redis).require_membership(org_id=org_id, user_id=claims.user_id)

    data = await AuditQueryService(db).list_logs(
        scope=scope,
        org_id=org_id if scope == "org" else None,
        actor_id=actor_id,
        resource_type=resource_type,
        page=page,
        page_size=page_size,
        search=search,
    )
    return success_response(data, meta.request_id, started, meta.timestamp)
