"""NANFO Backend - Report module SQLAlchemy ORM models.

Ownership: Report module exclusively owns these tables.
``__table_args__`` mirror every migration index/constraint (tests/unit/test_model_migration_parity.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
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
        Index("ix_reports_requested_at", "requested_at"),
        Index("ix_reports_history", "workspace_id", "requested_by_user_id", "requested_at", "report_id"),
        Index("ix_reports_worker", "status", "lease_expires_at"),
        CheckConstraint("status IN ('requested', 'running', 'generated', 'failed')", name="ck_reports_status"),
    )
    __mapper_args__ = {"eager_defaults": True}

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    network_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    report_type: Mapped[str] = mapped_column(Text, nullable=False)
    output_format: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="requested", server_default="requested")
    artifact_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Claims without a committed outcome (ADR-028 C20, migration 0030).
    claim_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    snapshot: Mapped[dict | None] = mapped_column(JSONB)
    snapshot_sha256: Mapped[str | None] = mapped_column(Text)
    receipt: Mapped[dict | None] = mapped_column(JSONB)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    date_range: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))

    artifact_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    error_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                                server_default=text("'{}'::jsonb"))

    queue_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    stream_entry_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    requested_by_user_id: Mapped[str] = mapped_column(Text, nullable=False)

    requested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ReportOutbox(Base):
    __tablename__ = "report_outbox"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "status_version", name="uq_report_outbox_version"
        ),
        Index("ix_report_outbox_pending", "published_at"),
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    # Same-module FK (migration 0030): retention deletes a report together with its
    # already published lifecycle events.
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.report_id", ondelete="CASCADE", name="fk_report_outbox_report"),
        nullable=False,
    )
    status_version: Mapped[int] = mapped_column(Integer, nullable=False)
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    stream_entry_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
