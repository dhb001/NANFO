"""Network-owned canonical spatial snapshot; its revision is assigned by the owner."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, BigInteger, CheckConstraint, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.modules.network.models import Network  # noqa: F401 -- register owning FK metadata


class SpatialSceneRecord(Base):
    __tablename__ = "network_spatial_scenes"
    __table_args__ = (
        CheckConstraint("revision >= 0 AND revision <= 9007199254740991", name="ck_spatial_scene_revision"),
    )

    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.network_id", ondelete="CASCADE"), primary_key=True,
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scene: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class SpatialSceneRevision(Base):
    """Immutable owner history; migration0022 installs write-protection triggers."""

    __tablename__ = "network_spatial_scene_revisions"
    __table_args__ = (
        CheckConstraint("revision >= 0 AND revision <= 9007199254740991", name="ck_spatial_history_revision"),
        CheckConstraint("origin IN ('baseline', 'replacement')", name="ck_spatial_history_origin"),
        CheckConstraint("origin = 'baseline' OR actor_id IS NOT NULL", name="ck_spatial_history_actor"),
    )

    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.network_id"), primary_key=True,
    )
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scene: Mapped[dict] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    # Logical Identity reference, never a cross-owner FK.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
