"""Telemetry-owned ADR023 scheduling/lease and durable prepublication spool."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class FleetDevice(Base):
    __tablename__ = "telemetry_fleet_devices"

    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    next_poll_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.clock_timestamp())
    failures: Mapped[int] = mapped_column(Integer, server_default="0")
    outcome: Mapped[str] = mapped_column(Text, server_default="never_collected")
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.clock_timestamp())
    last_published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    published_samples: Mapped[int] = mapped_column(Integer, server_default="0")
    expired_samples: Mapped[int] = mapped_column(Integer, server_default="0")


class FleetBatch(Base):
    __tablename__ = "telemetry_fleet_spool"
    __table_args__ = (
        CheckConstraint("status IN ('pending','published','expired','binding_changed')", name="ck_fleet_spool_status"),
        CheckConstraint("cursor >= 0 AND cursor <= jsonb_array_length(samples)", name="ck_fleet_spool_cursor"),
        Index("uq_fleet_spool_pending_device", "device_id", unique=True,
              postgresql_where=text("status = 'pending'")),
        Index("ix_fleet_spool_device_created", "device_id", "created_at"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("telemetry_fleet_devices.device_id"))
    binding_sha256: Mapped[str] = mapped_column(Text)
    samples: Mapped[list] = mapped_column(JSONB)
    cursor: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.clock_timestamp())
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
