"""0008_reporting_async_pipeline_baseline - Reporting persistence baseline for VS13.

Creates reports table for async generation/status and artifact lifecycle metadata.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("report_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("network_id", UUID(as_uuid=True), nullable=True),
        sa.Column("report_type", sa.Text(), nullable=False),
        sa.Column("output_format", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'requested'")),
        sa.Column("date_range", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("scope", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("filters", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("artifact_refs", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error_context", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("queue_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("stream_entry_id", sa.Text(), nullable=True),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_user_id", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_reports_workspace_idempotency",
        ),
    )

    op.create_index("ix_reports_workspace_id", "reports", ["workspace_id"])
    op.create_index("ix_reports_status", "reports", ["status"])
    op.create_index("ix_reports_requested_at", "reports", ["requested_at"])


def downgrade() -> None:
    op.drop_index("ix_reports_requested_at", table_name="reports")
    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_index("ix_reports_workspace_id", table_name="reports")
    op.drop_table("reports")
