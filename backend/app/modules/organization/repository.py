"""NANFO Backend — Organization module repository.

All DB operations for the Organization module.
No cross-module SQL joins. user_id in org_members is a stored reference only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization.models import Organization, OrgMember, Workspace


class OrganizationRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(self, name: str, slug: str) -> Organization:
        org = Organization(name=name, slug=slug)
        self._db.add(org)
        await self._db.flush()
        return org

    async def get_by_id(self, org_id: uuid.UUID) -> Organization | None:
        result = await self._db.execute(
            select(Organization).where(Organization.org_id == org_id, Organization.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self._db.execute(
            select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, page: int = 1, page_size: int = 20, org_id: uuid.UUID | None = None,
    ) -> tuple[list[Organization], int]:
        """Return organizations the user is a member of."""
        member_org_ids = select(OrgMember.org_id).where(OrgMember.user_id == user_id, OrgMember.deleted_at.is_(None))
        q = select(Organization).where(Organization.org_id.in_(member_org_ids), Organization.deleted_at.is_(None))
        if org_id is not None:
            q = q.where(Organization.org_id == org_id)
        total = (await self._db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await self._db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total

    async def soft_delete(self, org: Organization) -> None:
        from datetime import UTC, datetime
        org.deleted_at = datetime.now(UTC)
        await self._db.flush()

    async def update(self, org: Organization, *, name: str | None = None) -> Organization:
        if name is not None:
            org.name = name
        await self._db.flush()
        return org


class WorkspaceRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_accessible_ids(
        self, *, user_id: uuid.UUID, org_id: uuid.UUID | None, workspace_id: uuid.UUID | None,
    ) -> list[uuid.UUID]:
        query = (
            select(Workspace.workspace_id)
            .join(Organization, Organization.org_id == Workspace.org_id)
            .join(OrgMember, OrgMember.org_id == Organization.org_id)
            .where(
                Workspace.deleted_at.is_(None),
                Organization.deleted_at.is_(None),
                OrgMember.deleted_at.is_(None),
                OrgMember.user_id == user_id,
            )
            .order_by(Workspace.workspace_id)
        )
        if org_id is not None:
            query = query.where(Organization.org_id == org_id)
        if workspace_id is not None:
            query = query.where(Workspace.workspace_id == workspace_id)
        return list((await self._db.execute(query)).scalars().all())

    async def create(self, org_id: uuid.UUID, name: str, description: str | None) -> Workspace:
        ws = Workspace(org_id=org_id, name=name, description=description)
        self._db.add(ws)
        await self._db.flush()
        return ws

    async def get_by_id(self, workspace_id: uuid.UUID) -> Workspace | None:
        result = await self._db.execute(
            select(Workspace).where(Workspace.workspace_id == workspace_id, Workspace.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_org_id_for_workspace(self, workspace_id: uuid.UUID) -> uuid.UUID | None:
        result = await self._db.execute(
            select(Workspace.org_id).where(
                Workspace.workspace_id == workspace_id,
                Workspace.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_org(
        self, org_id: uuid.UUID, page: int = 1, page_size: int = 20, workspace_id: uuid.UUID | None = None,
    ) -> tuple[list[Workspace], int]:
        q = select(Workspace).where(Workspace.org_id == org_id, Workspace.deleted_at.is_(None))
        if workspace_id is not None:
            q = q.where(Workspace.workspace_id == workspace_id)
        total = (await self._db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await self._db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total

    async def soft_delete(self, workspace: Workspace) -> None:
        from datetime import UTC, datetime
        workspace.deleted_at = datetime.now(UTC)
        await self._db.flush()

    async def get_by_org_and_id(self, *, org_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace | None:
        result = await self._db.execute(
            select(Workspace).where(
                Workspace.workspace_id == workspace_id,
                Workspace.org_id == org_id,
                Workspace.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        workspace: Workspace,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Workspace:
        if name is not None:
            workspace.name = name
        if description is not None:
            workspace.description = description
        await self._db.flush()
        return workspace


class OrgMemberRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def add_member(self, org_id: uuid.UUID, user_id: uuid.UUID, org_role: str) -> OrgMember:
        member = OrgMember(org_id=org_id, user_id=user_id, org_role=org_role)
        self._db.add(member)
        await self._db.flush()
        return member

    async def get_member(self, org_id: uuid.UUID, user_id: uuid.UUID) -> OrgMember | None:
        result = await self._db.execute(
            select(OrgMember).where(
                OrgMember.org_id == org_id,
                OrgMember.user_id == user_id,
                OrgMember.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_members(self, org_id: uuid.UUID, page: int = 1, page_size: int = 20) -> tuple[list[OrgMember], int]:
        q = select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.deleted_at.is_(None))
        total = (await self._db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await self._db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total

    async def remove_member(self, member: OrgMember) -> None:
        from datetime import UTC, datetime
        member.deleted_at = datetime.now(UTC)
        await self._db.flush()
