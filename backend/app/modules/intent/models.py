"""NANFO Backend - Intent module SQLAlchemy ORM models.

Ownership: Intent module exclusively owns these tables.
Cross-module references (workspace_id, network_id) are logical UUID references.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Boolean, Float, Text, func
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
