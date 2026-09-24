"""ADR023 Autonomy-owned journals, persistent resource fences and measured frames."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class AutonomousResource(Base):
    __tablename__ = "autonomous_resources"

    resource_id: Mapped[str] = mapped_column(Text, primary_key=True)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class AutonomousExecution(Base):
    __tablename__ = "autonomous_executions"
    __table_args__ = (
        Index("uq_autonomous_resource_owned", "resource_id", unique=True,
              postgresql_where=text("released = false")),
        Index("uq_autonomous_decision", "decision_id", unique=True),
        Index("ix_autonomous_execution_pending", "updated_at",
              postgresql_where=text("released = false")),
        Index("ix_autonomous_executions_network_unreleased", "network_id",
              postgresql_where=text("released = false")),
        CheckConstraint("fence > 0", name="ck_autonomous_fence"),
        CheckConstraint("phase IN ('accepted','prepared','applying','verified','recovering','cancelled','uncertain')",
                        name="ck_autonomous_phase"),
        CheckConstraint("NOT released OR phase = 'cancelled'", name="ck_autonomous_release"),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # The fenced resource row is inserted (and locked) before its execution row.
    resource_id: Mapped[str] = mapped_column(
        Text, ForeignKey("autonomous_resources.resource_id", name="fk_autonomous_executions_resource"),
        nullable=False, index=True,
    )
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    command: Mapped[dict] = mapped_column(JSONB, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False, default="accepted")
    prepared: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    released: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.clock_timestamp())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.clock_timestamp())


class AutonomousObservation(Base):
    __tablename__ = "autonomous_observations"

    observation_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    observation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    safety_observation: Mapped[dict] = mapped_column(JSONB, nullable=False)


class AutonomousProviderState(Base):
    __tablename__ = "autonomous_provider_state"

    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    installation_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False)
