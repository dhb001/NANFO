"""NANFO Backend - Plugin module SQLAlchemy ORM models.

Ownership: Plugin module exclusively owns these tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Boolean, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class PluginRecord(Base):
    """Persisted registry flags and unverified declarations, never runtime state."""

    __tablename__ = "plugins"

    plugin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plugin_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    signature_status: Mapped[str] = mapped_column(Text, nullable=False, default="declared_unverified")
    dependency_status: Mapped[str] = mapped_column(Text, nullable=False, default="declared_unverified")
    sandbox_status: Mapped[str] = mapped_column(Text, nullable=False, default="not_executed")

    status: Mapped[str] = mapped_column(Text, nullable=False, default="installed")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    queue_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
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
