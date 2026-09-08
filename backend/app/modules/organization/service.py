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

        try:
            actor_user_id = uuid.UUID(actor_id)
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        org = await self._repo.create(name=req.name, slug=req.slug)
        await self._member_repo.add_member(org_id=org.org_id, user_id=actor_user_id, org_role="Admin")
        await self._db.commit()
        await self._db.refresh(org)

        try:
            await publish_event(
                redis=self._redis,
                event_type="org.organization.created",
                source="org",
                payload={"org_id": str(org.org_id), "name": org.name, "slug": org.slug, "actor_id": actor_id},
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "org_created_event_publish_failed",
                org_id=str(org.org_id),
                correlation_id=correlation_id,
                error=str(exc),
            )
        return OrgResponse.model_validate(org)

    async def list_orgs(
        self, user_id: str, page: int, page_size: int, org_id: uuid.UUID | None = None,
    ) -> OrgListResponse:
        rows, total = await self._repo.list_for_user(uuid.UUID(user_id), page=page, page_size=page_size, org_id=org_id)
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

    async def update_org(
        self,
        *,
        org_id: uuid.UUID,
        user_id: str,
        name: str | None,
        actor_id: str,
        correlation_id: str,
    ) -> OrgResponse:
        org = await self._repo.get_by_id(org_id)
        if org is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

        member = await self._member_repo.get_member(org_id, uuid.UUID(user_id))
        if member is None or member.org_role != "Admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        updated = await self._repo.update(org, name=name)
        await self._db.commit()
        await self._db.refresh(updated)

        changed_fields: dict[str, str] = {}
        if name is not None:
            changed_fields["name"] = updated.name

        try:
            await publish_event(
                redis=self._redis,
                event_type="org.organization.updated",
                source="org",
                payload={
                    "org_id": str(updated.org_id),
                    "changed_fields": changed_fields,
                    "actor_id": actor_id,
                },
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "org_updated_event_publish_failed",
                org_id=str(updated.org_id),
                correlation_id=correlation_id,
                error=str(exc),
            )

        return OrgResponse.model_validate(updated)

    async def delete_org(
        self,
        *,
        org_id: uuid.UUID,
        user_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> None:
        org = await self._repo.get_by_id(org_id)
        if org is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

        member = await self._member_repo.get_member(org_id, uuid.UUID(user_id))
        if member is None or member.org_role != "Admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        await self._repo.soft_delete(org)
        await self._db.commit()

        try:
            await publish_event(
                redis=self._redis,
                event_type="org.organization.deleted",
                source="org",
                payload={
                    "org_id": str(org.org_id),
                    "actor_id": actor_id,
                },
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "org_deleted_event_publish_failed",
                org_id=str(org.org_id),
                correlation_id=correlation_id,
                error=str(exc),
            )


class WorkspaceService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = WorkspaceRepository(db)
        self._org_repo = OrganizationRepository(db)
        self._member_repo = OrgMemberRepository(db)

    async def _assert_org_membership(
        self, *, org_id: uuid.UUID, user_id: str, require_admin: bool = False, require_write: bool = False,
    ) -> None:
        if await self._org_repo.get_by_id(org_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
        try:
            actor_user_id = uuid.UUID(user_id)
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        member = await self._member_repo.get_member(org_id, actor_user_id)
        if member is None or (require_admin and member.org_role != "Admin"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        if require_write and member.org_role not in {"Admin", "Operator"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

    async def assert_org_write_access(self, *, org_id: uuid.UUID, user_id: str) -> None:
        """Authorize org-scoped resource writes, not membership administration."""
        await self._assert_org_membership(org_id=org_id, user_id=user_id, require_write=True)

    async def list_accessible_workspace_ids(
        self,
        *,
        user_id: str,
        claim_org_id: uuid.UUID | None = None,
        claim_workspace_id: uuid.UUID | None = None,
    ) -> list[uuid.UUID]:
        """Return live membership scopes; optional claims only narrow access."""
        try:
            actor_id = uuid.UUID(user_id)
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return await self._repo.list_accessible_ids(
            user_id=actor_id, org_id=claim_org_id, workspace_id=claim_workspace_id,
        )

    async def assert_workspace_membership(
        self, *, workspace_id: uuid.UUID, user_id: str, require_write: bool = False,
    ) -> Workspace:
        """Resolve workspace and enforce that the user is a member of its org.

        This centralizes the `workspace -> org -> org_membership` ownership chain check
        for callers that only have a workspace identifier.
        """
        return await self.get_active_workspace(workspace_id, user_id=user_id, require_write=require_write)

    async def create_workspace(
        self,
        org_id: uuid.UUID,
        req: CreateWorkspaceRequest,
        actor_id: str,
        user_id: str,
        correlation_id: str,
    ) -> WorkspaceResponse:
        # Verify org exists
        org = await self._org_repo.get_by_id(org_id)
        if org is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

        await self._assert_org_membership(org_id=org_id, user_id=user_id, require_admin=True)

        ws = await self._repo.create(org_id=org_id, name=req.name, description=req.description)
        await self._db.commit()
        await self._db.refresh(ws)

        try:
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
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "workspace_created_event_publish_failed",
                workspace_id=str(ws.workspace_id),
                correlation_id=correlation_id,
                error=str(exc),
            )
        return WorkspaceResponse.model_validate(ws)

    async def list_workspaces(
        self,
        *,
        org_id: uuid.UUID,
        user_id: str,
        page: int,
        page_size: int,
        workspace_id: uuid.UUID | None = None,
    ) -> WorkspaceListResponse:
        await self._assert_org_membership(org_id=org_id, user_id=user_id)
        rows, total = await self._repo.list_for_org(org_id, page=page, page_size=page_size, workspace_id=workspace_id)
        return WorkspaceListResponse(items=[WorkspaceResponse.model_validate(r) for r in rows], total=total)

    async def get_workspace_for_org(
        self,
        *,
        org_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: str,
    ) -> WorkspaceResponse:
        await self._assert_org_membership(org_id=org_id, user_id=user_id)
        ws = await self._repo.get_by_org_and_id(org_id=org_id, workspace_id=workspace_id)
        if ws is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        return WorkspaceResponse.model_validate(ws)

    async def update_workspace(
        self,
        *,
        org_id: uuid.UUID,
        workspace_id: uuid.UUID,
        name: str | None,
        description: str | None,
        actor_id: str,
        user_id: str,
        correlation_id: str,
    ) -> WorkspaceResponse:
        await self._assert_org_membership(org_id=org_id, user_id=user_id, require_admin=True)

        ws = await self._repo.get_by_org_and_id(org_id=org_id, workspace_id=workspace_id)
        if ws is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")

        updated = await self._repo.update(ws, name=name, description=description)
        await self._db.commit()
        await self._db.refresh(updated)

        changed_fields: dict[str, str | None] = {}
        if name is not None:
            changed_fields["name"] = updated.name
        if description is not None:
            changed_fields["description"] = updated.description

        try:
            await publish_event(
                redis=self._redis,
                event_type="org.workspace.updated",
                source="org",
                payload={
                    "workspace_id": str(updated.workspace_id),
                    "org_id": str(updated.org_id),
                    "changed_fields": changed_fields,
                    "actor_id": actor_id,
                },
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "workspace_updated_event_publish_failed",
                workspace_id=str(updated.workspace_id),
                correlation_id=correlation_id,
                error=str(exc),
            )

        return WorkspaceResponse.model_validate(updated)

    async def delete_workspace(
        self,
        *,
        org_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_id: str,
        user_id: str,
        correlation_id: str,
    ) -> None:
        await self._assert_org_membership(org_id=org_id, user_id=user_id, require_admin=True)

        ws = await self._repo.get_by_org_and_id(org_id=org_id, workspace_id=workspace_id)
        if ws is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")

        await self._repo.soft_delete(ws)
        await self._db.commit()

        try:
            await publish_event(
                redis=self._redis,
                event_type="org.workspace.deleted",
                source="org",
                payload={
                    "workspace_id": str(ws.workspace_id),
                    "org_id": str(ws.org_id),
                    "actor_id": actor_id,
                },
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "workspace_deleted_event_publish_failed",
                workspace_id=str(ws.workspace_id),
                correlation_id=correlation_id,
                error=str(exc),
            )

    async def get_workspace(self, workspace_id: uuid.UUID) -> WorkspaceResponse:
        ws = await self.get_active_workspace(workspace_id)
        return WorkspaceResponse.model_validate(ws)

    async def get_active_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        user_id: str | None = None,
        claim_org_id: uuid.UUID | None = None,
        require_write: bool = False,
    ) -> Workspace:
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

        if user_id is not None:
            await self._assert_org_membership(org_id=ws.org_id, user_id=user_id, require_write=require_write)
        elif require_write:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        elif await self._org_repo.get_by_id(ws.org_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

        if claim_org_id is not None and ws.org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        return ws


class MemberService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = OrgMemberRepository(db)
        self._org_repo = OrganizationRepository(db)
        self._identity_directory = IdentityDirectoryService(db)

    async def _assert_actor_membership(
        self, *, org_id: uuid.UUID, actor_user_id: str, require_admin: bool = False,
    ) -> None:
        if await self._org_repo.get_by_id(org_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
        try:
            actor_id = uuid.UUID(actor_user_id)
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        member = await self._repo.get_member(org_id, actor_id)
        if member is None or (require_admin and member.org_role != "Admin"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

    async def add_member(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        org_role: str,
        actor_id: str,
        actor_user_id: str,
        correlation_id: str,
    ) -> MemberResponse:
        org = await self._org_repo.get_by_id(org_id)
        if org is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

        await self._assert_actor_membership(org_id=org_id, actor_user_id=actor_user_id, require_admin=True)

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

        try:
            await publish_event(
                redis=self._redis,
                event_type="org.member.added",
                source="org",
                payload={"org_id": str(org_id), "user_id": str(user_id), "org_role": org_role, "actor_id": actor_id},
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "org_member_added_event_publish_failed",
                org_id=str(org_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
                error=str(exc),
            )
        return MemberResponse.model_validate(member)

    async def list_members(
        self,
        *,
        org_id: uuid.UUID,
        actor_user_id: str,
        page: int,
        page_size: int,
    ) -> MemberListResponse:
        await self._assert_actor_membership(org_id=org_id, actor_user_id=actor_user_id)
        rows, total = await self._repo.list_members(org_id, page=page, page_size=page_size)
        return MemberListResponse(items=[MemberResponse.model_validate(r) for r in rows], total=total)

    async def remove_member(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        actor_id: str,
        actor_user_id: str,
        correlation_id: str,
    ) -> None:
        await self._assert_actor_membership(org_id=org_id, actor_user_id=actor_user_id, require_admin=True)

        member = await self._repo.get_member(org_id, user_id)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
        await self._repo.remove_member(member)
        await self._db.commit()
        try:
            await publish_event(
                redis=self._redis,
                event_type="org.member.removed",
                source="org",
                payload={"org_id": str(org_id), "user_id": str(user_id), "actor_id": actor_id},
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "org_member_removed_event_publish_failed",
                org_id=str(org_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
                error=str(exc),
            )
