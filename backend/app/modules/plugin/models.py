"""NANFO Backend - Plugin module SQLAlchemy ORM models.

Ownership: Plugin module exclusively owns these tables.
``__table_args__`` mirror every migration index/constraint (tests/unit/test_model_migration_parity.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Boolean, CheckConstraint, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class PluginRecord(Base):
    """Persisted registry flags and unverified declarations, never runtime state."""

    __tablename__ = "plugins"
    __table_args__ = (
        Index("ix_plugins_status", "status"),
        Index("ix_plugins_enabled", "enabled"),
        Index("ix_plugins_installed_at", "installed_at"),
        Index("ix_plugins_deferred_updated", "updated_at", postgresql_where=text("queue_status = 'deferred'")),
        CheckConstraint("queue_status IN ('pending', 'deferred', 'queued', 'not_applicable')",
                        name="ck_plugins_queue_status"),
    )
    __mapper_args__ = {"eager_defaults": True}

    plugin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    plugin_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))

    signature_status: Mapped[str] = mapped_column(Text, nullable=False, default="declared_unverified",
                                                  server_default="declared_unverified")
    dependency_status: Mapped[str] = mapped_column(Text, nullable=False, default="declared_unverified",
                                                   server_default="declared_unverified")
    sandbox_status: Mapped[str] = mapped_column(Text, nullable=False, default="not_executed",
                                                server_default="not_executed")

    status: Mapped[str] = mapped_column(Text, nullable=False, default="installed", server_default="installed")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    queue_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    stream_entry_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    installed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    uninstalled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
