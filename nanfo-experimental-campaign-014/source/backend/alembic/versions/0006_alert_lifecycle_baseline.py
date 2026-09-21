"""0006_alert_lifecycle_baseline - Alert persistence baseline for VS11 Step 1.

Creates alerts table for list/acknowledge/resolve lifecycle workflows.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("alert_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("alert_key", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("generated_event_id", UUID(as_uuid=True), nullable=True, unique=True),
        sa.Column("acknowledged_event_id", UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_event_id", UUID(as_uuid=True), nullable=True),
        sa.Column("acknowledged_by_user_id", sa.Text(), nullable=True),
        sa.Column("resolved_by_user_id", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_alerts_status", "alerts", ["status"])
    op.create_index("ix_alerts_alert_key", "alerts", ["alert_key"])
    op.create_index("ix_alerts_correlation_id", "alerts", ["correlation_id"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_alerts_created_at", table_name="alerts")
    op.drop_index("ix_alerts_correlation_id", table_name="alerts")
    op.drop_index("ix_alerts_alert_key", table_name="alerts")
    op.drop_index("ix_alerts_status", table_name="alerts")
    op.drop_table("alerts")
