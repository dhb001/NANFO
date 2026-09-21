"""Dedicated ADR025 Autonomy tables, independent of calibrated controls."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import TIMESTAMP, BigInteger, Boolean, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from .references import install_experimental_guards


class LabResource(Base):
    __tablename__ = "experimental_lab_resources"
    resource_id: Mapped[str] = mapped_column(Text, primary_key=True)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class LabRun(Base):
    __tablename__ = "experimental_lab_runs"
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("experimental_lab_resources.resource_id"), nullable=False)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    policy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    policy_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    stopped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    released: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    action_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_dispatched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class LabAction(Base):
    __tablename__ = "experimental_lab_actions"
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("experimental_lab_runs.run_id"), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    command: Mapped[dict | None] = mapped_column(JSONB)
    prepared: Mapped[dict | None] = mapped_column(JSONB)
    frame: Mapped[dict | None] = mapped_column(JSONB)
    inference: Mapped[dict | None] = mapped_column(JSONB)
    simulation: Mapped[dict | None] = mapped_column(JSONB)
    dispatched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class LabReceipt(Base):
    __tablename__ = "experimental_lab_receipts"
    receipt_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("experimental_lab_runs.run_id"), nullable=False, index=True)
    request_id: Mapped[UUID | None] = mapped_column(ForeignKey("experimental_lab_actions.request_id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


# Wire on model import, including direct repository/CLI writes without service import.
install_experimental_guards()
