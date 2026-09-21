"""Network-owned durable inventory events, separate from spatial inventory models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class NetworkOutbox(Base):
    __tablename__ = "network_outbox"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_network_outbox_attempts"),
        CheckConstraint(
            "(lease_token IS NULL) = (lease_until IS NULL)",
            name="ck_network_outbox_lease",
        ),
        Index(
            "ix_network_outbox_pending_network", "network_id", "sequence",
            postgresql_where=text("published_at IS NULL"),
        ),
        Index(
            "ix_network_outbox_due", "next_attempt_at", "sequence",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    # Logical owning-network reference: retained events survive inventory deletion.
    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(128))
