"""NANFO Backend — Telemetry module SQLAlchemy ORM models.

Ownership: Telemetry module exclusively owns telemetry_records.
``__table_args__`` mirror every migration index/constraint (tests/unit/test_model_migration_parity.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Float, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class TelemetryRecord(Base):
    """Append-only telemetry metric storage for VS2 Step 6 baseline."""

    __tablename__ = "telemetry_records"
    __table_args__ = (
        Index("ix_telemetry_records_network_id", "network_id"),
        Index("ix_telemetry_records_metric", "metric"),
        Index("ix_telemetry_records_observed_at", "observed_at"),
        Index("ix_telemetry_workspace_keyset", "workspace_id", "observed_at", "record_id"),
        Index("ix_telemetry_workspace_metric_keyset", "workspace_id", "metric", "observed_at", "record_id"),
        Index("ix_telemetry_network_keyset", "workspace_id", "network_id", "observed_at", "record_id"),
        Index("ix_telemetry_network_metric_keyset", "workspace_id", "network_id", "metric", "observed_at", "record_id"),
        # Per-device newest-first history (migration 0030; replaces ix_telemetry_records_device_id).
        Index("ix_telemetry_records_device_observed", "device_id", text("observed_at DESC"), text("record_id DESC")),
        # Compact time-range pruning for retention scans (migration 0030).
        Index("ix_telemetry_records_observed_at_brin", "observed_at", postgresql_using="brin"),
    )

    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    metric: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
