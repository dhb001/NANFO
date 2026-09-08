"""NANFO Backend — Organizations API router (/api/v1/organizations/*).

Implements Organization.md §3 endpoints with API_STANDARD.md §2 envelope.
All endpoints require JWT authentication.
"""

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    enforce_org_scope,
    enforce_workspace_scope,
    get_claim_org_scope,
    get_claim_workspace_scope,
    get_current_user,
    get_db,
    get_redis,
    get_request_meta,
    require_permissions,
)
from app.core.responses import APIResponse, success_response
from app.modules.organization.schemas import (
    AddMemberRequest,
    CreateOrgRequest,
    CreateWorkspaceRequest,
    MemberListResponse,
    MemberResponse,
    OrgListResponse,
    OrgResponse,
    UpdateOrgRequest,
    UpdateWorkspaceRequest,
    WorkspaceListResponse,
    WorkspaceResponse,
)
from app.modules.organization.service import MemberService, OrgService, WorkspaceService


async def _enforce_workspace_context(
    request: Request,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    workspace_id = get_claim_workspace_scope(claims=claims)
    raw_org_id = request.path_params.get("org_id")
    if workspace_id is not None and raw_org_id is not None:
        try:
            org_id = uuid.UUID(str(raw_org_id))
        except ValueError:
            return  # Path validation reports malformed resource identifiers.
        enforce_org_scope(claims=claims, org_id=org_id)
        await WorkspaceService(db=db, redis=redis).get_active_workspace(
            workspace_id, user_id=claims.user_id, claim_org_id=org_id,
        )


router = APIRouter(
    prefix="/api/v1/organizations", tags=["Organizations"], dependencies=[Depends(_enforce_workspace_context)],
)


# ── Organizations ─────────────────────────────────────────────────────────────

@router.post("", response_model=APIResponse[OrgResponse], status_code=status.HTTP_201_CREATED)
async def create_org(
    req: CreateOrgRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    svc = OrgService(db=db, redis=redis)
    result = await svc.create_org(req=req, actor_id=claims.user_id, correlation_id=meta.request_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("", response_model=APIResponse[OrgListResponse], status_code=status.HTTP_200_OK)
async def list_orgs(
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    page: int = 1,
    page_size: int = 20,
):
    started = time.monotonic()
    svc = OrgService(db=db, redis=redis)
    claim_org_id = get_claim_org_scope(claims=claims)
    claim_workspace_id = get_claim_workspace_scope(claims=claims)
    if claim_workspace_id is not None:
        workspace = await WorkspaceService(db=db, redis=redis).get_active_workspace(
            claim_workspace_id, user_id=claims.user_id, claim_org_id=claim_org_id,
        )
        claim_org_id = workspace.org_id
    result = await svc.list_orgs(user_id=claims.user_id, page=page, page_size=page_size, org_id=claim_org_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{org_id}", response_model=APIResponse[OrgResponse], status_code=status.HTTP_200_OK)
async def get_org(
    org_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    svc = OrgService(db=db, redis=redis)
    result = await svc.get_org(org_id=scoped_org_id, user_id=claims.user_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.patch("/{org_id}", response_model=APIResponse[OrgResponse], status_code=status.HTTP_200_OK)
async def update_org(
    org_id: uuid.UUID,
    req: UpdateOrgRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    svc = OrgService(db=db, redis=redis)
    result = await svc.update_org(
        org_id=scoped_org_id,
        user_id=claims.user_id,
        name=req.name,
        actor_id=claims.user_id,
        correlation_id=meta.request_id,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org(
    org_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    svc = OrgService(db=db, redis=redis)
    await svc.delete_org(
        org_id=scoped_org_id,
        user_id=claims.user_id,
        actor_id=claims.user_id,
        correlation_id=meta.request_id,
    )


# ── Workspaces ────────────────────────────────────────────────────────────────

@router.post("/{org_id}/workspaces", response_model=APIResponse[WorkspaceResponse], status_code=status.HTTP_201_CREATED)
async def create_workspace(
    org_id: uuid.UUID,
    req: CreateWorkspaceRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    svc = WorkspaceService(db=db, redis=redis)
    result = await svc.create_workspace(
        org_id=scoped_org_id,
        req=req,
        actor_id=claims.user_id,
        user_id=claims.user_id,
        correlation_id=meta.request_id,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{org_id}/workspaces", response_model=APIResponse[WorkspaceListResponse], status_code=status.HTTP_200_OK)
async def list_workspaces(
    org_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    page: int = 1,
    page_size: int = 20,
):
    started = time.monotonic()
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    svc = WorkspaceService(db=db, redis=redis)
    result = await svc.list_workspaces(
        org_id=scoped_org_id,
        user_id=claims.user_id,
        page=page,
        page_size=page_size,
        workspace_id=get_claim_workspace_scope(claims=claims),
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{org_id}/workspaces/{workspace_id}", response_model=APIResponse[WorkspaceResponse], status_code=status.HTTP_200_OK)
async def get_workspace(
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    enforce_workspace_scope(claims=claims, workspace_id=workspace_id)
    svc = WorkspaceService(db=db, redis=redis)
    result = await svc.get_workspace_for_org(
        org_id=scoped_org_id,
        workspace_id=workspace_id,
        user_id=claims.user_id,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.patch("/{org_id}/workspaces/{workspace_id}", response_model=APIResponse[WorkspaceResponse], status_code=status.HTTP_200_OK)
async def update_workspace(
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    req: UpdateWorkspaceRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    enforce_workspace_scope(claims=claims, workspace_id=workspace_id)
    svc = WorkspaceService(db=db, redis=redis)
    result = await svc.update_workspace(
        org_id=scoped_org_id,
        workspace_id=workspace_id,
        name=req.name,
        description=req.description,
        actor_id=claims.user_id,
        user_id=claims.user_id,
        correlation_id=meta.request_id,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.delete("/{org_id}/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    enforce_workspace_scope(claims=claims, workspace_id=workspace_id)
    svc = WorkspaceService(db=db, redis=redis)
    await svc.delete_workspace(
        org_id=scoped_org_id,
        workspace_id=workspace_id,
        actor_id=claims.user_id,
        user_id=claims.user_id,
        correlation_id=meta.request_id,
    )


# ── Members ───────────────────────────────────────────────────────────────────

@router.post("/{org_id}/members", response_model=APIResponse[MemberResponse], status_code=status.HTTP_201_CREATED)
async def add_member(
    org_id: uuid.UUID,
    req: AddMemberRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    svc = MemberService(db=db, redis=redis)
    result = await svc.add_member(
        org_id=scoped_org_id,
        user_id=req.user_id,
        org_role=req.org_role,
        actor_id=claims.user_id,
        actor_user_id=claims.user_id,
        correlation_id=meta.request_id,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{org_id}/members", response_model=APIResponse[MemberListResponse], status_code=status.HTTP_200_OK)
async def list_members(
    org_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    page: int = 1,
    page_size: int = 20,
):
    started = time.monotonic()
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    svc = MemberService(db=db, redis=redis)
    result = await svc.list_members(
        org_id=scoped_org_id,
        actor_user_id=claims.user_id,
        page=page,
        page_size=page_size,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    scoped_org_id = enforce_org_scope(claims=claims, org_id=org_id)
    svc = MemberService(db=db, redis=redis)
    await svc.remove_member(
        org_id=scoped_org_id,
        user_id=user_id,
        actor_id=claims.user_id,
        actor_user_id=claims.user_id,
        correlation_id=meta.request_id,
    )
