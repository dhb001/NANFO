"""NANFO Backend — Organization module service layer.

OrgService and WorkspaceService implement Organization.md requirements.
Cross-module constraint C5: workspace existence is validated here;
Network Service calls WorkspaceService.get_active_workspace() before creating networks.
"""

from __future__ import annotations

import uuid

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.identity.service import IdentityDirectoryService
from app.modules.organization.models import Workspace
from app.modules.organization.repository import (
    OrganizationRepository,
    OrgMemberRepository,
    WorkspaceRepository,
)
from app.modules.organization.schemas import (
    CreateOrgRequest,
    CreateWorkspaceRequest,
    MemberListResponse,
    MemberResponse,
    OrgListResponse,
    OrgResponse,
    WorkspaceListResponse,
    WorkspaceResponse,
)

logger = get_logger(__name__)


class OrgService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = OrganizationRepository(db)
        self._member_repo = OrgMemberRepository(db)

    async def create_org(self, req: CreateOrgRequest, actor_id: str, correlation_id: str) -> OrgResponse:
        # Slug uniqueness — 409 on conflict
        existing = await self._repo.get_by_slug(req.slug)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "ORG_SLUG_CONFLICT", "message": f"Slug '{req.slug}' is already taken."},
            )

        org = await self._repo.create(name=req.name, slug=req.slug)
        await self._db.commit()
        await self._db.refresh(org)

        await publish_event(
            redis=self._redis,
            event_type="org.organization.created",
            source="org",
            payload={"org_id": str(org.org_id), "name": org.name, "slug": org.slug, "actor_id": actor_id},
            correlation_id=correlation_id,
        )
        return OrgResponse.model_validate(org)

    async def list_orgs(self, user_id: str, page: int, page_size: int) -> OrgListResponse:
        rows, total = await self._repo.list_for_user(uuid.UUID(user_id), page=page, page_size=page_size)
        return OrgListResponse(items=[OrgResponse.model_validate(r) for r in rows], total=total)

    async def get_org(self, org_id: uuid.UUID, user_id: str) -> OrgResponse:
        org = await self._repo.get_by_id(org_id)
        if org is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
        # Verify membership (Organization.md §6 risk: cross-org data leakage)
        member = await self._member_repo.get_member(org_id, uuid.UUID(user_id))
        if member is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return OrgResponse.model_validate(org)


class WorkspaceService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = WorkspaceRepository(db)
        self._org_repo = OrganizationRepository(db)

    async def create_workspace(
        self, org_id: uuid.UUID, req: CreateWorkspaceRequest, actor_id: str, correlation_id: str
    ) -> WorkspaceResponse:
        # Verify org exists
        org = await self._org_repo.get_by_id(org_id)
        if org is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

        ws = await self._repo.create(org_id=org_id, name=req.name, description=req.description)
        await self._db.commit()
        await self._db.refresh(ws)

        await publish_event(
            redis=self._redis,
            event_type="org.workspace.created",
            source="org",
            payload={
                "workspace_id": str(ws.workspace_id),
                "org_id": str(org_id),
                "name": ws.name,
                "actor_id": actor_id,
            },
            correlation_id=correlation_id,
        )
        return WorkspaceResponse.model_validate(ws)

    async def list_workspaces(self, org_id: uuid.UUID, page: int, page_size: int) -> WorkspaceListResponse:
        rows, total = await self._repo.list_for_org(org_id, page=page, page_size=page_size)
        return WorkspaceListResponse(items=[WorkspaceResponse.model_validate(r) for r in rows], total=total)

    async def get_workspace(self, workspace_id: uuid.UUID) -> WorkspaceResponse:
        ws = await self._repo.get_by_id(workspace_id)
        if ws is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        return WorkspaceResponse.model_validate(ws)

    async def get_active_workspace(self, workspace_id: uuid.UUID) -> Workspace:
        """C5: Called by NetworkService to validate workspace existence before network creation.

        Returns the active Workspace object, or raises HTTP 404.
        This is a direct Python call within the modular monolith — no SQL join
        to any Network module tables is involved (ADR-004).
        """
        ws = await self._repo.get_by_id(workspace_id)
        if ws is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "WORKSPACE_NOT_FOUND", "message": "Workspace not found or has been deleted."},
            )
        return ws


class MemberService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = OrgMemberRepository(db)
        self._org_repo = OrganizationRepository(db)
        self._identity_directory = IdentityDirectoryService(db)

    async def add_member(
        self, org_id: uuid.UUID, user_id: uuid.UUID, org_role: str, actor_id: str, correlation_id: str
    ) -> MemberResponse:
        org = await self._org_repo.get_by_id(org_id)
        if org is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

        user_exists = await self._identity_directory.user_exists(user_id)
        if not user_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "USER_NOT_FOUND",
                    "message": "user_id does not reference an active user.",
                },
            )

        # Check duplicate membership
        existing = await self._repo.get_member(org_id, user_id)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a member.")

        member = await self._repo.add_member(org_id=org_id, user_id=user_id, org_role=org_role)
        await self._db.commit()

        await publish_event(
            redis=self._redis,
            event_type="org.member.added",
            source="org",
            payload={"org_id": str(org_id), "user_id": str(user_id), "org_role": org_role, "actor_id": actor_id},
            correlation_id=correlation_id,
        )
        return MemberResponse.model_validate(member)

    async def list_members(self, org_id: uuid.UUID, page: int, page_size: int) -> MemberListResponse:
        rows, total = await self._repo.list_members(org_id, page=page, page_size=page_size)
        return MemberListResponse(items=[MemberResponse.model_validate(r) for r in rows], total=total)

    async def remove_member(
        self, org_id: uuid.UUID, user_id: uuid.UUID, actor_id: str, correlation_id: str
    ) -> None:
        member = await self._repo.get_member(org_id, user_id)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
        await self._repo.remove_member(member)
        await self._db.commit()
        await publish_event(
            redis=self._redis,
            event_type="org.member.removed",
            source="org",
            payload={"org_id": str(org_id), "user_id": str(user_id), "actor_id": actor_id},
            correlation_id=correlation_id,
        )
