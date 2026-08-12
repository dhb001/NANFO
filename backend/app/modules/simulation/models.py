"""NANFO Backend - Simulation module SQLAlchemy ORM models.

Ownership: Simulation module exclusively owns these tables.
Cross-module references (network_id, workspace_id) are logical UUID references.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Simulation(Base):
    """Persisted simulation lifecycle state and compare-ready run metadata."""

    __tablename__ = "simulations"

    simulation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_simulation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("simulations.simulation_id", ondelete="SET NULL"),
        nullable=True,
    )

    # Cross-module logical references (no SQL FKs to network module tables).
    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    scenario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scenario_name: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    risk_gate: Mapped[str] = mapped_column(Text, nullable=False)

    validation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    run_output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    audit_provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    queue_status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
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
