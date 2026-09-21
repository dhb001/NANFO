"""Telemetry-owned archive receipts, permanent dedup and reconciliation state."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Boolean, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class TelemetryEventTombstone(Base):
    __tablename__ = "telemetry_event_tombstones"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.clock_timestamp())


class TelemetryArchiveReceipt(Base):
    __tablename__ = "telemetry_archive_receipts"

    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    archived_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.clock_timestamp())
    restored_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class TelemetryReconciliation(Base):
    __tablename__ = "telemetry_reference_reconciliation"

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner: Mapped[str] = mapped_column(Text, primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unknown: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.clock_timestamp())
