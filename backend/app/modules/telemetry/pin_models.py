"""Telemetry-owned durable reference coverage and non-expiring evidence pins."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class TelemetryEvidencePin(Base):
    __tablename__ = "telemetry_evidence_pins"
    __table_args__ = (
        CheckConstraint("owner IN ('report','intent','alert','simulation','autonomy')", name="ck_telemetry_pin_owner"),
        # Includes released records: the FK intentionally retains their audit linkage.
        Index("ix_telemetry_pins_record", "record_id"),
        Index("ix_telemetry_pins_active", "workspace_id", "record_id", postgresql_where=text("released_at IS NULL")),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner: Mapped[str] = mapped_column(Text, primary_key=True)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telemetry_records.record_id", ondelete="RESTRICT"), primary_key=True,
    )
    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.clock_timestamp())
    released_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class TelemetryReferenceCoverage(Base):
    __tablename__ = "telemetry_reference_coverage"
    __table_args__ = (
        CheckConstraint("owner IN ('report','intent','alert','simulation','autonomy')", name="ck_telemetry_coverage_owner"),
        CheckConstraint("version = 1", name="ck_telemetry_coverage_version"),
        CheckConstraint("contract = 'pin-before-reference/v1'", name="ck_telemetry_coverage_contract"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    contract: Mapped[str] = mapped_column(Text, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.clock_timestamp())
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
