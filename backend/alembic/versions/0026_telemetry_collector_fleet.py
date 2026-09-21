"""ADR023 Telemetry fleet leases and durable prepublish spool, after retention0025."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op
from app.modules.telemetry.fleet_models import FleetBatch, FleetDevice  # noqa: F401 -- owning metadata

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telemetry_fleet_devices",
        sa.Column("device_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", pg.UUID(as_uuid=True)),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_until", sa.TIMESTAMP(timezone=True)),
        sa.Column("next_poll_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome", sa.Text(), nullable=False, server_default="never_collected"),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.Column("last_published_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("published_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expired_samples", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "telemetry_fleet_spool",
        sa.Column("batch_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", pg.UUID(as_uuid=True), sa.ForeignKey("telemetry_fleet_devices.device_id"), nullable=False),
        sa.Column("binding_sha256", sa.Text(), nullable=False),
        sa.Column("samples", pg.JSONB(), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint("status IN ('pending','published','expired','binding_changed')", name="ck_fleet_spool_status"),
        sa.CheckConstraint("cursor >= 0 AND cursor <= jsonb_array_length(samples)", name="ck_fleet_spool_cursor"),
    )
    op.create_index("uq_fleet_spool_pending_device", "telemetry_fleet_spool", ["device_id"], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))
    op.create_index("ix_fleet_spool_device_created", "telemetry_fleet_spool", ["device_id", "created_at"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM telemetry_fleet_spool WHERE status = 'pending')")):
        raise RuntimeError("Pending fleet spool must be drained or expired before downgrade")
    op.drop_table("telemetry_fleet_spool")
    op.drop_table("telemetry_fleet_devices")
