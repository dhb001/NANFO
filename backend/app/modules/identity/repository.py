"""NANFO Backend — Identity module repository.

All DB operations for the Identity module.
No cross-module SQL joins permitted (ADR-004, database.md §2).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.identity.models import AuditLog, Role, User, UserRole


class UserRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_by_email(self, email: str) -> User | None:
        result = await self._db.execute(
            select(User)
            .where(User.email == email, User.deleted_at.is_(None))
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._db.execute(
            select(User)
            .where(User.user_id == user_id, User.deleted_at.is_(None))
            .execution_options(populate_existing=True)
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
        )
        return result.scalar_one_or_none()

    async def create(self, email: str, hashed_password: str, display_name: str | None = None) -> User:
        user = User(email=email, hashed_password=hashed_password, display_name=display_name)
        self._db.add(user)
        await self._db.flush()
        return user

    async def get_roles_for_user(self, user: User) -> list[str]:
        result = await self._db.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.role_id)
            .where(UserRole.user_id == user.user_id)
        )
        return list(result.scalars().all())

    async def get_permissions_for_roles(self, role_names: list[str]) -> list[str]:
        if not role_names:
            return []
        # For this slice permissions are static seed data; fetch all for matching roles.
        # Full permission mapping is deferred to a dedicated RBAC service in M3 full pass.
        from app.modules.identity.models import Permission
        result = await self._db.execute(select(Permission))
        all_perms = result.scalars().all()
        # Admin role gets all permissions; others get read-only subset
        if "Admin" in role_names:
            return [p.name for p in all_perms]
        if any(role in role_names for role in ("Operator", "Read-Only")):
            return ["read:topology", "read:telemetry"]
        return []

    async def assign_role(self, user_id: uuid.UUID, role_name: str) -> None:
        role_result = await self._db.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role '{role_name}' not found.")
        mapping = UserRole(user_id=user_id, role_id=role.role_id)
        self._db.add(mapping)
        await self._db.flush()


class AuditLogRepository:
    """INSERT-only repository for the immutable audit_logs table (Authentication.md §4)."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def append(
        self,
        *,
        event_type: str,
        actor_id: uuid.UUID | None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID,
        metadata: dict | None = None,
    ) -> AuditLog:
        """Append an immutable audit log record. Never updates existing records."""
        entry = AuditLog(
            event_type=event_type,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            org_id=org_id,
            correlation_id=correlation_id,
            metadata_=metadata,
        )
        self._db.add(entry)
        await self._db.flush()
        return entry

    async def list_entries(
        self,
        *,
        actor_id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuditLog], int]:
        from sqlalchemy import func, select
        q = select(AuditLog)
        if actor_id:
            q = q.where(AuditLog.actor_id == actor_id)
        if org_id:
            q = q.where(AuditLog.org_id == org_id)
        if resource_type:
            q = q.where(AuditLog.resource_type == resource_type)
        q = q.order_by(AuditLog.timestamp.desc())

        count_q = select(func.count()).select_from(q.subquery())
        total = (await self._db.execute(count_q)).scalar_one()

        q = q.offset((page - 1) * page_size).limit(page_size)
        rows = (await self._db.execute(q)).scalars().all()
        return list(rows), total
