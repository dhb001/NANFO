"""Telemetry archival, permanent event dedup and reconciliation (ADR023).

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("telemetry_event_tombstones",
        sa.Column("event_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("record_id", pg.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False))
    op.create_table("telemetry_archive_receipts",
        sa.Column("record_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", pg.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
        sa.Column("restored_at", sa.TIMESTAMP(timezone=True)))
    op.create_index("ix_telemetry_archive_receipts_workspace_id", "telemetry_archive_receipts", ["workspace_id"])
    op.create_table("telemetry_reference_reconciliation",
        sa.Column("workspace_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner", sa.Text(), primary_key=True),
        sa.Column("cursor", sa.Text()),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unknown", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False))
    # Existing manual prospective claims are not evidence of owner integration.
    op.execute("UPDATE telemetry_reference_coverage SET revoked_at = clock_timestamp() WHERE revoked_at IS NULL")


def downgrade():
    # Dropping dedup/archive receipts after deletion would lose replay safety.
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM telemetry_archive_receipts)")):
        raise RuntimeError("Restore/archive and dedup history require retention0025; downgrade refused")
    op.drop_table("telemetry_reference_reconciliation")
    op.drop_table("telemetry_archive_receipts")
    op.drop_table("telemetry_event_tombstones")
