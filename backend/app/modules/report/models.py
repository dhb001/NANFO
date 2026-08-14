"""NANFO Backend - Report module SQLAlchemy ORM models.

Ownership: Report module exclusively owns these tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class ReportRecord(Base):
    """Persisted report lifecycle metadata and artifact references."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_reports_workspace_idempotency",
        ),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    network_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    report_type: Mapped[str] = mapped_column(Text, nullable=False)
    output_format: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="requested")

    date_range: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    artifact_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    queue_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    stream_entry_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requested_by_user_id: Mapped[str] = mapped_column(Text, nullable=False)

    requested_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
