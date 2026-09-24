"""NANFO Backend — Organization module SQLAlchemy ORM models.

Ownership: Organization module exclusively owns these tables (Organization.md §4, ADR-004).
org_members.user_id is a logical reference to Identity module — NO SQL FK to users table.
``__table_args__`` mirror every migration index/constraint (tests/unit/test_model_migration_parity.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


class Organization(Base):
    __tablename__ = "organizations"
    __mapper_args__ = {"eager_defaults": True}

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # The unique constraint's index serves lookups (the duplicate ix_organizations_slug is dropped in 0030).
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    workspaces: Mapped[list["Workspace"]] = relationship(back_populates="organization")
    members: Mapped[list["OrgMember"]] = relationship(back_populates="organization")


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (Index("ix_workspaces_org_id", "org_id"),)
    __mapper_args__ = {"eager_defaults": True}

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    # org_id FK is within-module (Organization owns both tables)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="workspaces")


class OrgMember(Base):
    __tablename__ = "org_members"
    __table_args__ = (
        Index("ix_org_members_user_id", "user_id"),
        CheckConstraint("org_role IN ('Admin', 'Operator', 'Read-Only')", name="ck_org_members_org_role"),
    )

    # org_id FK is within-module
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.org_id", ondelete="CASCADE"), primary_key=True
    )
    # user_id: LOGICAL REFERENCE only — no SQL FK to Identity module (ADR-004)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    org_role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="members")
