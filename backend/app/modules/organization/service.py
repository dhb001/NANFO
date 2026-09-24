"""NANFO Backend — Organization module service layer.

OrgService and WorkspaceService implement Organization.md requirements.
Cross-module constraint C5: workspace existence is validated here;
Network Service calls WorkspaceService.get_active_workspace() before creating networks.

ADR-028:
  * C6 — ``GET`` of an organization returns the same 404 for "absent" and "not a
    member"; responses carry the caller's org role (``caller_role``); slug
    conflicts use a generic message.
  * Authorization is decided with plain reads first, so an unauthorized caller
    never takes or queues for the organization row lock; authorized callers
    then lock and re-check, because authority may change while waiting.
  * Organization never imports the Network module at import time: workspace
    deletion asks a narrow ``WorkspaceInventory`` port (default adapter imports
    NetworkService lazily), breaking the organization ↔ network cycle.
"""

from __future__ import annotations

import uuid
from typing import Protocol

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.identity.audit import project_event_metadata
from app.modules.identity.service import IdentityDirectoryService, append_audit_log
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

ORG_ROLES = ("Admin", "Operator", "Read-Only")
_WRITE_ROLES = frozenset({"Admin", "Operator"})
_SLUG_CONFLICT = {"code": "ORG_SLUG_CONFLICT", "message": "Organization slug is unavailable."}


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")


def _org_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")


def _parse_actor(user_id: object) -> uuid.UUID | None:
    try:
        return user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except (TypeError, ValueError, AttributeError):
        return None


def _require_actor(user_id: object) -> uuid.UUID:
    actor = _parse_actor(user_id)
    if actor is None:
        raise _forbidden()
    return actor


def _role_or_none(value: object) -> str | None:
    role = getattr(value, "org_role", value)
    return role if isinstance(role, str) and role in ORG_ROLES else None


def _org_response(org, *, caller_role: object) -> OrgResponse:
    return OrgResponse(org_id=org.org_id, name=org.name, slug=org.slug, created_at=org.created_at,
                       caller_role=_role_or_none(caller_role))


async def _authorized_member(
    org_repo: OrganizationRepository, member_repo: OrgMemberRepository, *,
    org_id: uuid.UUID, actor: uuid.UUID, require_admin: bool = False, require_write: bool = False,
):
    """Plain-read authority check: active org, active membership, sufficient role."""
    if await org_repo.get_by_id(org_id) is None:
        raise _org_not_found()
    member = await member_repo.get_member(org_id, actor)
    if member is None or (require_admin and member.org_role != "Admin"):
        raise _forbidden()
    if require_write and member.org_role not in _WRITE_ROLES:
        raise _forbidden()
    return member


async def _commit_lifecycle(db, redis, *, event_type: str, payload: dict, correlation_id: str) -> None:
    """Commit owned mutation and Identity audit together, then publish the same identity."""
    event_id = uuid.uuid4()
    entity = event_type.split(".")[1]
    resource_type, key = {
        "organization": ("organization", "org_id"),
        "workspace": ("workspace", "workspace_id"),
        "member": ("org_member", "user_id"),
    }[entity]
    try:
        # Same allowlisted projection the audit consumer persists on replay.
        await append_audit_log(
            db=db, event_id=event_id, event_type=event_type,
            actor_id=uuid.UUID(payload["actor_id"]), resource_type=resource_type,
            resource_id=uuid.UUID(payload[key]), org_id=uuid.UUID(payload["org_id"]),
            correlation_id=correlation_id, metadata=project_event_metadata(event_type, payload),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    try:
        await publish_event(redis=redis, event_id=str(event_id), event_type=event_type,
                            source="org", payload=payload, correlation_id=correlation_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("org_lifecycle_event_publish_failed", event_id=str(event_id),
                       event_type=event_type, correlation_id=correlation_id, error=str(exc))


class WorkspaceInventory(Protocol):
    """Narrow port: does a workspace still own active network inventory?"""

    async def has_active_networks(self, *, workspace_id: uuid.UUID, actor_user_id: str) -> bool: ...


class NetworkServiceInventory:
    """Default ``WorkspaceInventory`` over the Network module's public service.

    Imported lazily at call time so Organization never imports Network at module
    import (Network depends on Organization, not the reverse). Never queries
    Network tables directly (ADR-004).
    """

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis

    async def has_active_networks(self, *, workspace_id: uuid.UUID, actor_user_id: str) -> bool:
        from app.modules.network.service import NetworkService

        page = await NetworkService(self._db, self._redis).list_networks(
            workspace_id=workspace_id, actor_user_id=actor_user_id, page=1, page_size=1,
        )
        return bool(page.total)


class OrgService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = OrganizationRepository(db)
        self._member_repo = OrgMemberRepository(db)

    async def _authorize_admin_locked(self, org_id: uuid.UUID, user_id: str):
        """Authorize (plain read), then lock the org row and re-check under the lock."""
        actor = _require_actor(user_id)
        await _authorized_member(self._repo, self._member_repo, org_id=org_id, actor=actor, require_admin=True)
        await self._repo.lock(org_id)
        await _authorized_member(self._repo, self._member_repo, org_id=org_id, actor=actor, require_admin=True)
        org = await self._repo.get_by_id(org_id)
        if org is None:
            raise _org_not_found()
        return org

    async def create_org(self, req: CreateOrgRequest, actor_id: str, correlation_id: str) -> OrgResponse:
        # Slug uniqueness — 409 on conflict (deleted slugs stay reserved; message is generic)
        existing = await self._repo.get_by_slug(req.slug)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_SLUG_CONFLICT)

        actor_user_id = _require_actor(actor_id)

        try:
            org = await self._repo.create(name=req.name, slug=req.slug)
        except IntegrityError as exc:
            await self._db.rollback()
            # Translate only the expected concurrent slug conflict.
            if getattr(exc.orig, "sqlstate", None) == "23505" and await self._repo.get_by_slug(req.slug) is not None:
                raise HTTPException(status_code=409, detail=_SLUG_CONFLICT) from exc
            raise
        await self._member_repo.add_member(org_id=org.org_id, user_id=actor_user_id, org_role="Admin")
        await _commit_lifecycle(self._db, self._redis, event_type="org.organization.created",
                                payload={"org_id": str(org.org_id), "name": org.name,
                                         "slug": org.slug, "actor_id": actor_id}, correlation_id=correlation_id)
        return _org_response(org, caller_role="Admin")

    async def list_orgs(
        self, user_id: str, page: int, page_size: int, org_id: uuid.UUID | None = None,
        *, include_caller_role: bool = False,
    ) -> OrgListResponse:
        actor = _require_actor(user_id)
        rows, total = await self._repo.list_for_user(actor, page=page, page_size=page_size, org_id=org_id)
        items = []
        for row in rows:
            role = _role_or_none(getattr(row, "caller_role", None))
            if include_caller_role and role is None:
                # Repository rows carry the role; this fallback only serves other row sources.
                role = _role_or_none(await self._member_repo.get_member(row.org_id, actor))
            items.append(_org_response(row, caller_role=role))
        return OrgListResponse(items=items, total=total)

    async def get_caller_role(self, *, org_id: uuid.UUID, user_id: str) -> str | None:
        """Caller's current role in an active organization; None when absent or not a member."""
        actor = _parse_actor(user_id)
        if actor is None or await self._repo.get_by_id(org_id) is None:
            return None
        return _role_or_none(await self._member_repo.get_member(org_id, actor))

    async def require_membership(self, *, org_id: uuid.UUID, user_id: str) -> str:
        """Authorization check for resources narrowed by an org: 403 when absent or not a member.

        Use this (not ``get_org``) when an organization gates access to another
        resource; ``get_org`` is the organization read and answers 404 (C6).
        """
        role = await self.get_caller_role(org_id=org_id, user_id=user_id)
        if role is None:
            raise _forbidden()
        return role

    async def get_org(self, org_id: uuid.UUID, user_id: str) -> OrgResponse:
        # C6 / Organization.md §6 (cross-org leakage): absent and not-a-member are
        # indistinguishable, so an organization's existence is never disclosed.
        org = await self._repo.get_by_id(org_id)
        actor = _parse_actor(user_id)
        member = await self._member_repo.get_member(org_id, actor) if org is not None and actor is not None else None
        if org is None or member is None:
            raise _org_not_found()
        return _org_response(org, caller_role=member)

    async def update_org(
        self,
        *,
        org_id: uuid.UUID,
        user_id: str,
        name: str | None,
        actor_id: str,
        correlation_id: str,
    ) -> OrgResponse:
        org = await self._authorize_admin_locked(org_id, user_id)

        updated = await self._repo.update(org, name=name)

        changed_fields: dict[str, str] = {}
        if name is not None:
            changed_fields["name"] = updated.name

        await _commit_lifecycle(self._db, self._redis, event_type="org.organization.updated",
                                payload={"org_id": str(updated.org_id), "changed_fields": changed_fields,
                                         "actor_id": actor_id}, correlation_id=correlation_id)

        return _org_response(updated, caller_role="Admin")

    async def delete_org(
        self,
        *,
        org_id: uuid.UUID,
        user_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> None:
        org = await self._authorize_admin_locked(org_id, user_id)

        _, total = await WorkspaceRepository(self._db).list_for_org(org_id, page_size=1)
        if total:
            raise HTTPException(status_code=409, detail={
                "code": "ORG_HAS_WORKSPACES", "message": "Delete active workspaces before deleting the organization.",
            })
        await self._repo.soft_delete(org)
        await _commit_lifecycle(self._db, self._redis, event_type="org.organization.deleted",
                                payload={"org_id": str(org.org_id), "actor_id": actor_id}, correlation_id=correlation_id)


class WorkspaceService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis, *, inventory: WorkspaceInventory | None = None):
        self._db = db
        self._redis = redis
        self._repo = WorkspaceRepository(db)
        self._org_repo = OrganizationRepository(db)
        self._member_repo = OrgMemberRepository(db)
        self._inventory = inventory

    async def _assert_org_membership(
        self, *, org_id: uuid.UUID, user_id: str, require_admin: bool = False, require_write: bool = False,
        lock_for_write: bool = True,
    ) -> None:
        actor = _require_actor(user_id)
        # Authorize with plain reads first: an unauthorized caller never takes,
        # or queues for, the organization row lock.
        await _authorized_member(self._org_repo, self._member_repo, org_id=org_id, actor=actor,
                                 require_admin=require_admin, require_write=require_write)
        if require_admin:
            await self._org_repo.lock(org_id)
        elif require_write and lock_for_write:
            try:
                await self._org_repo.lock(org_id, shared=True)
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) != "55P03":
                    raise
                raise HTTPException(status_code=409, detail={
                    "code": "ORG_AUTHORITY_BUSY",
                    "message": "Organization authority is changing. Retry the operation.",
                }) from exc
        else:
            return
        # Authority (membership, role, org liveness) may have changed while waiting.
        await _authorized_member(self._org_repo, self._member_repo, org_id=org_id, actor=actor,
                                 require_admin=require_admin, require_write=require_write)

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
        actor_id = _require_actor(user_id)
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
            raise _org_not_found()

        await self._assert_org_membership(org_id=org_id, user_id=user_id, require_admin=True)

        ws = await self._repo.create(org_id=org_id, name=req.name, description=req.description)
        await _commit_lifecycle(self._db, self._redis, event_type="org.workspace.created",
                                payload={"workspace_id": str(ws.workspace_id), "org_id": str(org_id),
                                         "name": ws.name, "actor_id": actor_id}, correlation_id=correlation_id)
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
        description_provided: bool = False,
    ) -> WorkspaceResponse:
        await self._assert_org_membership(org_id=org_id, user_id=user_id, require_admin=True)

        ws = await self._repo.get_by_org_and_id(org_id=org_id, workspace_id=workspace_id)
        if ws is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")

        updated = await self._repo.update(ws, name=name, description=description,
                                          description_provided=description_provided)

        changed_fields: dict[str, str | None] = {}
        if name is not None:
            changed_fields["name"] = updated.name
        if description is not None or description_provided:
            changed_fields["description"] = updated.description

        await _commit_lifecycle(self._db, self._redis, event_type="org.workspace.updated",
                                payload={"workspace_id": str(updated.workspace_id), "org_id": str(updated.org_id),
                                         "changed_fields": changed_fields, "actor_id": actor_id}, correlation_id=correlation_id)

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

        # Ask the owning module through a narrow port, never query Network tables
        # here. The org lock also serializes inventory creation through get_active_workspace.
        inventory = self._inventory or NetworkServiceInventory(self._db, self._redis)
        if await inventory.has_active_networks(workspace_id=workspace_id, actor_user_id=user_id):
            raise HTTPException(status_code=409, detail={
                "code": "WORKSPACE_HAS_NETWORKS", "message": "Delete active networks before deleting the workspace.",
            })
        await self._repo.soft_delete(ws)
        await _commit_lifecycle(self._db, self._redis, event_type="org.workspace.deleted",
                                payload={"workspace_id": str(ws.workspace_id), "org_id": str(ws.org_id),
                                         "actor_id": actor_id}, correlation_id=correlation_id)

    async def check_workspace_write_authority(self, workspace_id: uuid.UUID, *, user_id: str) -> Workspace:
        """Read current authority without retaining a tenant mutation fence.

        For observers with their own post-lock/precommit fresh-session checks.
        Never use this in place of the parent fence for inventory creation: a
        fresh observer must not wait behind a revoker waiting on its caller.
        """
        return await self.get_active_workspace(workspace_id, user_id=user_id,
                                               require_write=True, lock_for_write=False)

    async def get_active_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        user_id: str | None = None,
        claim_org_id: uuid.UUID | None = None,
        require_write: bool = False,
        lock_for_write: bool = True,
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
            if lock_for_write:
                await self._assert_org_membership(org_id=ws.org_id, user_id=user_id, require_write=require_write)
            else:
                await self._assert_org_membership(org_id=ws.org_id, user_id=user_id,
                                                  require_write=require_write, lock_for_write=False)
            if require_write:
                # A delete may have committed while waiting for the org lock.
                ws = await self._repo.get_by_id(workspace_id)
                if ws is None:
                    raise HTTPException(status_code=404, detail="Workspace not found.")
        elif require_write:
            raise _forbidden()
        elif await self._org_repo.get_by_id(ws.org_id) is None:
            raise _org_not_found()

        if claim_org_id is not None and ws.org_id != claim_org_id:
            raise _forbidden()

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
        actor = _require_actor(actor_user_id)
        # Plain-read authorization first; only authorized administrators lock.
        await _authorized_member(self._org_repo, self._repo, org_id=org_id, actor=actor,
                                 require_admin=require_admin)
        if not require_admin:
            return
        await self._org_repo.lock(org_id)
        # A completed revocation must deny an actor that was waiting on the lock.
        await _authorized_member(self._org_repo, self._repo, org_id=org_id, actor=actor, require_admin=True)

    async def add_member(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        org_role: str,
        actor_id: str,
        actor_user_id: str,
        correlation_id: str,
    ) -> MemberResponse:
        if org_role not in ORG_ROLES:
            raise HTTPException(status_code=422, detail="Invalid organization role.")
        org = await self._org_repo.get_by_id(org_id)
        if org is None:
            raise _org_not_found()

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
        existing = await self._repo.get_member(org_id, user_id, include_deleted=True)
        if existing is not None and existing.deleted_at is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a member.")

        member = await self._repo.add_member(org_id=org_id, user_id=user_id, org_role=org_role)
        await _commit_lifecycle(self._db, self._redis, event_type="org.member.added",
                                payload={"org_id": str(org_id), "user_id": str(user_id),
                                         "org_role": org_role, "actor_id": actor_id,
                                         "restored": existing is not None}, correlation_id=correlation_id)
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
        if member.org_role == "Admin":
            usable_admin = False
            for admin_id in await self._repo.list_admin_ids(org_id):
                if admin_id != user_id and await self._identity_directory.can_administer_organization(admin_id):
                    usable_admin = True
                    break
            if not usable_admin:
                raise HTTPException(status_code=409, detail={
                    "code": "ORG_LAST_ADMIN", "message": "Add another active Admin before removing the last Admin.",
                })
        await self._repo.remove_member(member)
        await _commit_lifecycle(self._db, self._redis, event_type="org.member.removed",
                                payload={"org_id": str(org_id), "user_id": str(user_id), "actor_id": actor_id},
                                correlation_id=correlation_id)
