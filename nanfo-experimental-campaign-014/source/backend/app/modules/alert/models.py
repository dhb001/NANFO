"""NANFO Backend - Alert module SQLAlchemy ORM models.

Ownership: Alert module exclusively owns these tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class AlertRecord(Base):
    """Persisted alert lifecycle state for list/acknowledge/resolve workflows."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index("uq_alert_measured_incident", "detector_key", unique=True,
              postgresql_where=text("detector_key IS NOT NULL AND status != 'resolved'")),
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_key: Mapped[str] = mapped_column(Text, nullable=False)
    detector_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    generated_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        unique=True,
    )
    acknowledged_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    acknowledged_by_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AlertDetectorState(Base):
    __tablename__ = "alert_detector_states"

    detector_key: Mapped[str] = mapped_column(Text, primary_key=True)
    identity: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rule: Mapped[dict] = mapped_column(JSONB, nullable=False)
    last_observed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    phase: Mapped[str | None] = mapped_column(Text)
    phase_since: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.alert_id"))


class AlertObservation(Base):
    __tablename__ = "alert_observations"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    detector_key: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class AlertConsumedEvent(Base):
    """Durable first-delivery receipts, including suppressed legacy generations."""

    __tablename__ = "alert_consumed_events"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    payload_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.alert_id"))
    consumed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class AlertHistory(Base):
    __tablename__ = "alert_history"
    __table_args__ = (Index("ix_alert_history_incident", "alert_id", "occurred_at", "event_id"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.alert_id"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class AlertOutbox(Base):
    __tablename__ = "alert_outbox"
    __table_args__ = (Index("ix_alert_outbox_pending", "published_at"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alert_history.event_id"), primary_key=True)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
