"""ADR022 telemetry evidence pins, prospective coverage and bounded keyset indexes."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op
from app.modules.telemetry.pin_models import (  # noqa: F401 -- owning metadata
    TelemetryEvidencePin,
    TelemetryReferenceCoverage,
)

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telemetry_evidence_pins",
        sa.Column("workspace_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner", sa.Text(), primary_key=True),
        sa.Column("reference_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("record_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("telemetry_records.record_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("network_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.Column("released_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint("owner IN ('report','intent','alert','simulation','autonomy')", name="ck_telemetry_pin_owner"),
    )
    # Includes released records: the FK intentionally retains their audit linkage.
    op.create_index("ix_telemetry_pins_record", "telemetry_evidence_pins", ["record_id"])
    op.create_index("ix_telemetry_pins_active", "telemetry_evidence_pins", ["workspace_id", "record_id"],
                    postgresql_where=sa.text("released_at IS NULL"))
    op.create_table(
        "telemetry_reference_coverage",
        sa.Column("workspace_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("contract", sa.Text(), nullable=False),
        sa.Column("registered_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint("owner IN ('report','intent','alert','simulation','autonomy')", name="ck_telemetry_coverage_owner"),
        sa.CheckConstraint("version = 1", name="ck_telemetry_coverage_version"),
        sa.CheckConstraint("contract = 'pin-before-reference/v1'", name="ck_telemetry_coverage_contract"),
    )
    for name, columns in (
        ("ix_telemetry_workspace_keyset", ["workspace_id", "observed_at", "record_id"]),
        ("ix_telemetry_workspace_metric_keyset", ["workspace_id", "metric", "observed_at", "record_id"]),
        ("ix_telemetry_network_keyset", ["workspace_id", "network_id", "observed_at", "record_id"]),
        ("ix_telemetry_network_metric_keyset", ["workspace_id", "network_id", "metric", "observed_at", "record_id"]),
    ):
        op.create_index(name, "telemetry_records", columns)


def downgrade():
    for name in (
        "ix_telemetry_network_metric_keyset", "ix_telemetry_network_keyset",
        "ix_telemetry_workspace_metric_keyset", "ix_telemetry_workspace_keyset",
    ):
        op.drop_index(name, table_name="telemetry_records")
    op.drop_table("telemetry_reference_coverage")
    op.drop_table("telemetry_evidence_pins")
