"""NANFO Backend — Identity module repository.

All DB operations for the Identity module.
No cross-module SQL joins permitted (ADR-004, database.md §2).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from app.core.correlation import correlation_uuid
from app.modules.identity.models import AuditLog, Role, User, UserRole
from app.modules.identity.policy import permissions_for_roles


class UserRepository:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_by_email(self, email: str) -> User | None:
        # Roles are read once by get_roles_for_user; never implicitly re-loaded here.
        result = await self._db.execute(
            select(User)
            .where(User.email == email, User.deleted_at.is_(None))
            .options(raiseload(User.user_roles))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._db.execute(
            select(User)
            .where(User.user_id == user_id, User.deleted_at.is_(None))
            .execution_options(populate_existing=True)
            .options(raiseload(User.user_roles))
        )
        return result.scalar_one_or_none()

    async def create(self, email: str, hashed_password: str, display_name: str | None = None) -> User:
        user = User(email=email, hashed_password=hashed_password, display_name=display_name)
        self._db.add(user)
        await self._db.flush()
        return user

    async def get_roles_for_user(self, user: User) -> list[str]:
        """Current global role names — the single role read per authorization."""
        result = await self._db.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.role_id)
            .where(UserRole.user_id == user.user_id)
            .order_by(Role.name)
        )
        return list(result.scalars().all())

    async def get_permissions_for_roles(self, role_names: list[str]) -> list[str]:
        """Declared role → permission policy (identity.policy); no per-request query.

        Kept async so the repository contract (and its test doubles) is unchanged.
        """
        return permissions_for_roles(role_names)

    async def assign_role(self, user_id: uuid.UUID, role_name: str) -> None:
        role_result = await self._db.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role '{role_name}' not found.")
        mapping = UserRole(user_id=user_id, role_id=role.role_id)
        self._db.add(mapping)
        await self._db.flush()

    # ── Account mutations (callers revoke sessions after commit; ADR-028 C9) ──

    async def set_active(self, user_id: uuid.UUID, active: bool) -> bool:
        """Set ``is_active``; True when an existing, non-deleted user changed state."""
        result = await self._db.execute(
            update(User)
            .where(User.user_id == user_id, User.deleted_at.is_(None), User.is_active.is_not(active))
            .values(is_active=active)
            .returning(User.user_id)
            .execution_options(synchronize_session=False)
        )
        return result.scalar_one_or_none() is not None

    async def set_password_hash(self, user_id: uuid.UUID, hashed_password: str) -> bool:
        result = await self._db.execute(
            update(User)
            .where(User.user_id == user_id, User.deleted_at.is_(None))
            .values(hashed_password=hashed_password)
            .returning(User.user_id)
            .execution_options(synchronize_session=False)
        )
        return result.scalar_one_or_none() is not None

    async def replace_roles(self, user_id: uuid.UUID, role_names: Iterable[str]) -> tuple[list[str], list[str]]:
        """Replace the user's global roles; returns (before, after) role names."""
        wanted = sorted(set(role_names))
        roles = list((await self._db.execute(select(Role).where(Role.name.in_(wanted)))).scalars().all())
        missing = set(wanted) - {role.name for role in roles}
        if missing:
            raise ValueError(f"Unknown roles: {', '.join(sorted(missing))}.")
        before = list((await self._db.execute(
            select(Role.name).join(UserRole, UserRole.role_id == Role.role_id)
            .where(UserRole.user_id == user_id).order_by(Role.name)
        )).scalars().all())
        await self._db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        for role in roles:
            self._db.add(UserRole(user_id=user_id, role_id=role.role_id))
        await self._db.flush()
        return before, wanted


def _audit_search_clause(term: str):
    """UUID terms match UUID columns exactly; other terms are literal ILIKE on text columns.

    UUID columns are never cast to text. An opaque request identifier additionally
    matches the correlation UUID it deterministically maps to (app.core.correlation).
    """
    try:
        value = uuid.UUID(term)
    except (ValueError, AttributeError, TypeError):
        value = None
    if value is not None:
        return or_(
            AuditLog.correlation_id == value, AuditLog.resource_id == value,
            AuditLog.actor_id == value, AuditLog.event_id == value, AuditLog.log_id == value,
        )
    return or_(
        AuditLog.event_type.icontains(term, autoescape=True),
        AuditLog.resource_type.icontains(term, autoescape=True),
        AuditLog.correlation_id == correlation_uuid(term),
    )


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
        event_id: uuid.UUID | None = None,
    ) -> AuditLog | None:
        """Append an immutable audit log record. Never updates existing records."""
        if event_id is not None:
            # Identity and effect commit together; a crash/replay cannot add a row.
            result = await self._db.execute(
                insert(AuditLog).values(
                    event_id=event_id, event_type=event_type, actor_id=actor_id,
                    resource_type=resource_type, resource_id=resource_id, org_id=org_id,
                    correlation_id=correlation_id, metadata_=metadata,
                ).on_conflict_do_nothing(index_elements=[AuditLog.event_id]).returning(AuditLog)
            )
            return result.scalar_one_or_none()
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
        search: str | None = None,
        platform_only: bool = False,
    ) -> tuple[list[AuditLog], int]:
        """Filtered, deterministically ordered page of audit rows.

        ``platform_only`` selects unscoped (``org_id IS NULL``) platform events such
        as authentication; otherwise ``org_id`` (when given) scopes to one org.
        """
        q = select(AuditLog)
        if platform_only:
            q = q.where(AuditLog.org_id.is_(None))
        elif org_id:
            q = q.where(AuditLog.org_id == org_id)
        if actor_id:
            q = q.where(AuditLog.actor_id == actor_id)
        if resource_type:
            q = q.where(AuditLog.resource_type == resource_type)
        term = search.strip() if search else ""
        if term:
            q = q.where(_audit_search_clause(term))
        q = q.order_by(AuditLog.timestamp.desc(), AuditLog.log_id.desc())

        count_q = select(func.count()).select_from(q.order_by(None).subquery())
        total = (await self._db.execute(count_q)).scalar_one()

        q = q.offset((page - 1) * page_size).limit(page_size)
        rows = (await self._db.execute(q)).scalars().all()
        return list(rows), total
