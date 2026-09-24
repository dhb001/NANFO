"""NANFO Backend - Simulation module SQLAlchemy ORM models.

Ownership: Simulation module exclusively owns these tables.
Cross-module references (network_id, workspace_id) are logical UUID references.
``__table_args__`` mirror every migration index/constraint (tests/unit/test_model_migration_parity.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base

SIMULATION_STATES = ("draft", "queued", "running", "paused", "completed", "cancelled", "failed")
_STATES = "(" + ", ".join(f"'{state}'" for state in SIMULATION_STATES) + ")"


class Simulation(Base):
    """Persisted simulation lifecycle state and compare-ready run metadata."""

    __tablename__ = "simulations"
    __table_args__ = (
        Index("ix_simulations_network_id", "network_id"),
        Index("ix_simulations_workspace_id", "workspace_id"),
        Index("ix_simulations_scenario_id", "scenario_id"),
        Index("ix_simulations_parent_simulation_id", "parent_simulation_id"),
        Index("ix_simulations_state", "state"),
        Index("ix_simulations_modeled_due", "state", "lease_expires_at",
              postgresql_where=text("scenario_config IS NOT NULL")),
        # Not-yet-terminal simulations of a network (simulation/queries.py has_blocking_work).
        Index("ix_simulations_network_active", "network_id",
              postgresql_where=text("status NOT IN ('cancelled', 'completed', 'failed')")),
        CheckConstraint(f"state IN {_STATES}", name="ck_simulations_state"),
        CheckConstraint(f"status IN {_STATES}", name="ck_simulations_status"),
    )
    __mapper_args__ = {"eager_defaults": True}

    simulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
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

    validation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    run_output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    model_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                                 server_default=text("'{}'::jsonb"))
    audit_provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                                   server_default=text("'{}'::jsonb"))

    scenario_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    checkpoint: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    input_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Claims without committed progress (ADR-028 C20, migration 0030).
    claim_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    evidence_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    queue_status: Mapped[str] = mapped_column(Text, nullable=False, default="queued", server_default="queued")
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


class SimulationOutbox(Base):
    __tablename__ = "simulation_outbox"
    __table_args__ = (
        UniqueConstraint("simulation_id", "revision", name="uq_simulation_outbox_revision"),
        Index("ix_simulation_outbox_pending", "published_at", postgresql_where=text("published_at IS NULL")),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    simulation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("simulations.simulation_id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
