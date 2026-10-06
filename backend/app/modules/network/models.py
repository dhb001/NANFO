"""NANFO Backend — Network module SQLAlchemy ORM models.

Ownership: Network module exclusively owns these tables (Topology.md §4, ADR-004).
networks.workspace_id is a logical reference to Organization module — NO SQL FK.
``__table_args__`` mirror every migration index/constraint (tests/unit/test_model_migration_parity.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, Float, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base

# Every mapper with an ``onupdate`` column returns server values with the flush (C8:
# responses carry the real ``updated_at`` without a lazy load).
_EAGER = {"eager_defaults": True}


class Network(Base):
    __tablename__ = "networks"
    __table_args__ = (Index("ix_networks_workspace_id", "workspace_id"),)
    __mapper_args__ = _EAGER

    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    # workspace_id: LOGICAL REFERENCE only — no SQL FK to Organization module (ADR-004, C5)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cidr: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    devices: Mapped[list["Device"]] = relationship(back_populates="network")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        Index("ix_devices_network_id", "network_id"),
        Index("ix_devices_hostname", "hostname"),
        Index("ix_devices_spatial_ref_id", "spatial_ref_id"),
    )
    __mapper_args__ = _EAGER

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    # network_id FK is within-module (Network owns both tables)
    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.network_id", ondelete="CASCADE"), nullable=False
    )
    hostname: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    device_type: Mapped[str] = mapped_column(Text, nullable=False)
    vendor: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    # location_hint: intentionally ephemeral free text.
    # Will be superseded by spatial_ref_id (UOM reference) in M6 Digital Twin slice.
    location_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    # spatial_ref_id: Digital Twin/UOM spatial object reference.
    spatial_ref_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    network: Mapped["Network"] = relationship(back_populates="devices")


class CampusBuildingRecord(Base):
    __tablename__ = "campus_buildings"
    __table_args__ = (
        Index("ix_campus_buildings_network_id", "network_id"),
        Index("ix_campus_buildings_building_id", "building_id"),
        # Arbiter of the repository's ON CONFLICT upsert (migration 0030 deduplicated).
        Index("uq_campus_buildings_network_building_active", "network_id", "building_id", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
    )
    __mapper_args__ = _EAGER

    campus_building_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.network_id", ondelete="CASCADE"), nullable=False
    )
    building_id: Mapped[str] = mapped_column(Text, nullable=False)
    campus_key: Mapped[str] = mapped_column(Text, nullable=False)
    building_key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    geometry: Mapped[str] = mapped_column(Text, nullable=False)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    z: Mapped[float] = mapped_column(Float, nullable=False)
    base_y: Mapped[float] = mapped_column(Float, nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False)
    depth: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    floors: Mapped[int] = mapped_column(Integer, nullable=False)
    footprint: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    wall_material: Mapped[str | None] = mapped_column(Text, nullable=True)
    attenuation_db: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class CampusModelAssetRecord(Base):
    __tablename__ = "campus_model_assets"
    __table_args__ = (
        Index("ix_campus_model_assets_network_id", "network_id"),
        CheckConstraint(
            "(storage_backend = 'inline' AND model_data_base64 IS NOT NULL) "
            "OR (storage_backend = 'local_cas' AND model_data_base64 IS NULL "
            "AND model_sha256 ~ '^[0-9a-f]{64}$' AND model_size_bytes BETWEEN 1 AND 8388608)",
            name="ck_campus_asset_storage",
        ),
    )
    __mapper_args__ = _EAGER

    campus_model_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.network_id", ondelete="CASCADE"), nullable=False
    )
    model_file_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    model_data_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_backend: Mapped[str] = mapped_column(Text, nullable=False, default="inline", server_default="inline")
    registration: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    model_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mapping_by_device_id: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                                       server_default=text("'{}'::jsonb"))
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class DeviceGroup(Base):
    __tablename__ = "device_groups"
    __table_args__ = (
        Index("ix_device_groups_network_id", "network_id"),
        Index("uq_device_groups_network_group_key_active", "network_id", "group_key", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
    )
    __mapper_args__ = _EAGER

    device_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    network_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.network_id", ondelete="CASCADE"), nullable=False
    )
    group_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    group_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    selector: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class DeviceGroupMember(Base):
    __tablename__ = "device_group_members"
    __table_args__ = (
        Index("ix_device_group_members_group_id", "device_group_id"),
        Index("ix_device_group_members_device_id", "device_id"),
        Index("uq_device_group_members_group_device_active", "device_group_id", "device_id", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
    )

    device_group_member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    device_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("device_groups.device_group_id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
