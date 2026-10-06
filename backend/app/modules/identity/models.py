"""NANFO Backend — Identity module SQLAlchemy ORM models.

Ownership: Identity module exclusively owns these tables (Authentication.md §4, ADR-004).
No other module queries these tables directly.
audit_logs is immutable — no UPDATE or DELETE ever executed (Authentication.md §4).
``__table_args__`` mirror every migration index/constraint (tests/unit/test_model_migration_parity.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Boolean, ForeignKey, Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    user_roles: Mapped[list["UserRole"]] = relationship(back_populates="role")


class Permission(Base):
    __tablename__ = "permissions"

    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)


class User(Base):
    __tablename__ = "users"
    __mapper_args__ = {"eager_defaults": True}

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    # The unique constraint's index serves lookups (the duplicate ix_users_email is dropped in 0030).
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # hashed_password is NEVER returned in any API response or event payload
    # (Authentication.md §5, security.md)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    user_roles: Mapped[list["UserRole"]] = relationship(back_populates="user", lazy="selectin")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), primary_key=True, index=True,
    )

    user: Mapped["User"] = relationship(back_populates="user_roles")
    role: Mapped["Role"] = relationship(back_populates="user_roles")


class AuditLog(Base):
    """Immutable audit log. INSERT only — no UPDATE or DELETE (Authentication.md §4)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_audit_logs_event_id"),
        Index("ix_audit_logs_actor_id", "actor_id"),
        Index("ix_audit_logs_event_type", "event_type"),
        Index("ix_audit_logs_timestamp", "timestamp"),
        # Org-scoped audit pages, newest first (migration 0030, built CONCURRENTLY).
        Index("ix_audit_logs_org_timestamp", "org_id", text('"timestamp" DESC'), text("log_id DESC")),
    )

    log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
