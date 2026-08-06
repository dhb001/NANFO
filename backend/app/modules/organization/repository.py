"""NANFO Backend — Organization module repository.

All DB operations for the Organization module.
No cross-module SQL joins. user_id in org_members is a stored reference only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization.models import OrgMember, Organization, Workspace


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

    async def list_for_user(self, user_id: uuid.UUID, page: int = 1, page_size: int = 20) -> tuple[list[Organization], int]:
        """Return organizations the user is a member of."""
        member_org_ids = select(OrgMember.org_id).where(OrgMember.user_id == user_id, OrgMember.deleted_at.is_(None))
        q = select(Organization).where(Organization.org_id.in_(member_org_ids), Organization.deleted_at.is_(None))
        total = (await self._db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await self._db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total

    async def soft_delete(self, org: Organization) -> None:
        from datetime import UTC, datetime
        org.deleted_at = datetime.now(UTC)
        await self._db.flush()


class WorkspaceRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

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

    async def list_for_org(self, org_id: uuid.UUID, page: int = 1, page_size: int = 20) -> tuple[list[Workspace], int]:
        q = select(Workspace).where(Workspace.org_id == org_id, Workspace.deleted_at.is_(None))
        total = (await self._db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await self._db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total

    async def soft_delete(self, workspace: Workspace) -> None:
        from datetime import UTC, datetime
        workspace.deleted_at = datetime.now(UTC)
        await self._db.flush()


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
