"""NANFO Backend — Organizations API router (/api/v1/organizations/*).

Implements Organization.md §3 endpoints with API_STANDARD.md §2 envelope.
All endpoints require JWT authentication.
"""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    get_current_user,
    get_db,
    get_redis,
    get_request_meta,
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
    WorkspaceListResponse,
    WorkspaceResponse,
)
from app.modules.organization.service import MemberService, OrgService, WorkspaceService

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])


# ── Organizations ─────────────────────────────────────────────────────────────

@router.post("", response_model=APIResponse[OrgResponse], status_code=status.HTTP_201_CREATED)
async def create_org(
    req: CreateOrgRequest,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
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
    redis=Depends(get_redis),
    page: int = 1,
    page_size: int = 20,
):
    started = time.monotonic()
    svc = OrgService(db=db, redis=redis)
    result = await svc.list_orgs(user_id=claims.user_id, page=page, page_size=page_size)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{org_id}", response_model=APIResponse[OrgResponse], status_code=status.HTTP_200_OK)
async def get_org(
    org_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
):
    started = time.monotonic()
    svc = OrgService(db=db, redis=redis)
    result = await svc.get_org(org_id=org_id, user_id=claims.user_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


# ── Workspaces ────────────────────────────────────────────────────────────────

@router.post("/{org_id}/workspaces", response_model=APIResponse[WorkspaceResponse], status_code=status.HTTP_201_CREATED)
async def create_workspace(
    org_id: uuid.UUID,
    req: CreateWorkspaceRequest,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
):
    started = time.monotonic()
    svc = WorkspaceService(db=db, redis=redis)
    result = await svc.create_workspace(org_id=org_id, req=req, actor_id=claims.user_id, correlation_id=meta.request_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{org_id}/workspaces", response_model=APIResponse[WorkspaceListResponse], status_code=status.HTTP_200_OK)
async def list_workspaces(
    org_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
    page: int = 1,
    page_size: int = 20,
):
    started = time.monotonic()
    svc = WorkspaceService(db=db, redis=redis)
    result = await svc.list_workspaces(org_id=org_id, page=page, page_size=page_size)
    return success_response(result, meta.request_id, started, meta.timestamp)


# ── Members ───────────────────────────────────────────────────────────────────

@router.post("/{org_id}/members", response_model=APIResponse[MemberResponse], status_code=status.HTTP_201_CREATED)
async def add_member(
    org_id: uuid.UUID,
    req: AddMemberRequest,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
):
    started = time.monotonic()
    svc = MemberService(db=db, redis=redis)
    result = await svc.add_member(org_id=org_id, user_id=req.user_id, org_role=req.org_role, actor_id=claims.user_id, correlation_id=meta.request_id)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{org_id}/members", response_model=APIResponse[MemberListResponse], status_code=status.HTTP_200_OK)
async def list_members(
    org_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
    page: int = 1,
    page_size: int = 20,
):
    started = time.monotonic()
    svc = MemberService(db=db, redis=redis)
    result = await svc.list_members(org_id=org_id, page=page, page_size=page_size)
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
):
    svc = MemberService(db=db, redis=redis)
    await svc.remove_member(org_id=org_id, user_id=user_id, actor_id=claims.user_id, correlation_id=meta.request_id)
