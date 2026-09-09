"""NANFO Backend - Intent module SQLAlchemy ORM models.

Ownership: Intent module exclusively owns these tables.
Cross-module references (workspace_id, network_id) are logical UUID references.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Intent(Base):
    """Persisted intent lifecycle state, provenance, and explainability metadata."""

    __tablename__ = "intents"

    intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Cross-module logical references (no SQL FKs to non-owning module tables).
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    network_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    intent_kind: Mapped[str] = mapped_column(Text, nullable=False)
    intent_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    validation_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    execution_provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    explainability: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_band: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    queue_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    stream_entry_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_by_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class IntentExecution(Base):
    """Immutable approval/command identity plus leased reconciliation state."""

    __tablename__ = "intent_executions"
    __table_args__ = (
        UniqueConstraint("intent_id", name="uq_intent_executions_intent"),
        UniqueConstraint("workspace_id", "request_key", name="uq_intent_executions_request"),
        Index("uq_intent_executions_blocking_lab", "lab_key", unique=True, postgresql_where=text("blocks_lab")),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    intent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("intents.intent_id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_key: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    lab_key: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    approved_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    command: Mapped[dict] = mapped_column(JSONB, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False, default="accepted")
    blocks_lab: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancelled_by_user_id: Mapped[str | None] = mapped_column(Text)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    outbox_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    fence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class IntentOutbox(Base):
    __tablename__ = "intent_outbox"
    __table_args__ = (UniqueConstraint("execution_id", "sequence", name="uq_intent_outbox_sequence"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("intent_executions.execution_id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
