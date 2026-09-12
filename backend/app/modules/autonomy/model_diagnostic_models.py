"""Autonomy-owned, append-only historical inference evidence."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class ModelDiagnostic(Base):
    __tablename__ = "autonomy_model_diagnostics"
    __table_args__ = (Index("ix_model_diagnostics_scope_created", "network_id", "workspace_id", "created_at", "diagnostic_id"),)

    diagnostic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
