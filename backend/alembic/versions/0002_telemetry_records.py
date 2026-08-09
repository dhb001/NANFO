"""0002_telemetry_records — Telemetry persistence baseline for VS2 Step 6.

Creates telemetry_records table owned by Telemetry module.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_records",
        sa.Column("record_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", UUID(as_uuid=True), nullable=False),
        sa.Column("network_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("tags", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_telemetry_records_device_id", "telemetry_records", ["device_id"])
    op.create_index("ix_telemetry_records_network_id", "telemetry_records", ["network_id"])
    op.create_index("ix_telemetry_records_workspace_id", "telemetry_records", ["workspace_id"])
    op.create_index("ix_telemetry_records_metric", "telemetry_records", ["metric"])
    op.create_index("ix_telemetry_records_observed_at", "telemetry_records", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_telemetry_records_observed_at", table_name="telemetry_records")
    op.drop_index("ix_telemetry_records_metric", table_name="telemetry_records")
    op.drop_index("ix_telemetry_records_workspace_id", table_name="telemetry_records")
    op.drop_index("ix_telemetry_records_network_id", table_name="telemetry_records")
    op.drop_index("ix_telemetry_records_device_id", table_name="telemetry_records")
    op.drop_table("telemetry_records")
