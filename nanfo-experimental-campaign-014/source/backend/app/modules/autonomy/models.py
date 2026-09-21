"""Autonomy-owned tables; references to other modules are logical UUIDs only."""

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class AutonomyControl(Base):
    __tablename__ = "autonomy_controls"
    __table_args__ = (
        CheckConstraint("mode IN ('monitor', 'recommend', 'autonomous')", name="ck_autonomy_mode"),
        CheckConstraint("cancellation_status IN ('none', 'requested', 'verified', 'uncertain')",
                        name="ck_autonomy_cancellation_status"),
        CheckConstraint("revision >= 0", name="ck_autonomy_revision"),
        CheckConstraint("(active_execution_id IS NULL AND active_intent_id IS NULL AND active_decision_id IS NULL) "
                        "OR (active_execution_id IS NOT NULL AND active_intent_id IS NOT NULL AND active_decision_id IS NOT NULL)",
                        name="ck_autonomy_execution_identity"),
        Index("ix_autonomy_controls_due", "next_cycle_at", "network_id",
              postgresql_where=text("(approved_by_user_id IS NOT NULL OR active_execution_id IS NOT NULL) AND (NOT emergency_stopped OR active_execution_id IS NOT NULL)")),
        Index("uq_autonomy_controls_execution", "active_execution_id", unique=True),
    )

    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="monitor")
    checkpoint_sha256: Mapped[str | None] = mapped_column(Text)
    approval_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    approved_by_user_id: Mapped[str | None] = mapped_column(Text)
    emergency_stopped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stopped_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    stopped_by_user_id: Mapped[str | None] = mapped_column(Text)
    active_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    active_intent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    active_decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cancellation_status: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    next_cycle_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    last_observation: Mapped[dict | None] = mapped_column(JSONB)
    last_accepted_observed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class AutonomyDecision(Base):
    __tablename__ = "autonomy_decisions"
    __table_args__ = (
        Index("ix_autonomy_decisions_network_created", "network_id", "created_at", "decision_id"),
        Index("ix_autonomy_decisions_observing", "network_id", postgresql_where=text("status = 'observing'")),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    network_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("autonomy_controls.network_id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    control_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    checkpoint_sha256: Mapped[str | None] = mapped_column(Text)
    observation: Mapped[dict | None] = mapped_column(JSONB)
    proposal: Mapped[dict | None] = mapped_column(JSONB)
    safety: Mapped[dict | None] = mapped_column(JSONB)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verification: Mapped[dict | None] = mapped_column(JSONB)
    authorization: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class ConfigurationRevision(Base):
    __tablename__ = "autonomy_configuration_revisions"

    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    operational: Mapped[dict] = mapped_column(JSONB, nullable=False)
    training: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class TimedOverride(Base):
    __tablename__ = "autonomy_overrides"
    __table_args__ = (
        Index("uq_autonomy_override_unresolved", "network_id", unique=True,
              postgresql_where=text("status IN ('holding', 'restoring')")),
        Index("uq_autonomy_override_execution", "execution_id", unique=True),
        Index("ix_autonomy_override_due", "next_check_at", "lease_expires_at",
              postgresql_where=text("status IN ('holding', 'restoring', 'restored')")),
    )

    override_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    return_mode: Mapped[str] = mapped_column(Text, nullable=False)
    prior_mode: Mapped[str] = mapped_column(Text, nullable=False)
    prior_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    hold_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoint_sha256: Mapped[str | None] = mapped_column(Text)
    prior_approval_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    prior_approved_by_user_id: Mapped[str | None] = mapped_column(Text)
    command_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    plan_hash: Mapped[str] = mapped_column(Text, nullable=False)
    binding_digest: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    configuration_verified_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    recovery_reference: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    cancellation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    cancelled_by_user_id: Mapped[str | None] = mapped_column(Text)
    restoration_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification: Mapped[dict | None] = mapped_column(JSONB)
    restored_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    return_requested_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    return_requested_by_user_id: Mapped[str | None] = mapped_column(Text)
    return_reason: Mapped[str | None] = mapped_column(Text)
    returned_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    next_check_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
