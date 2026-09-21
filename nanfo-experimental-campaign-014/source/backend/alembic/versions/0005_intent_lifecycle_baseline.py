"""0005_intent_lifecycle_baseline - Intent persistence baseline for VS8 Step 2.

Creates intents table for lifecycle state, validation/execution provenance,
and explainability/confidence metadata.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intents",
        sa.Column("intent_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("network_id", UUID(as_uuid=True), nullable=True),
        sa.Column("intent_kind", sa.Text(), nullable=False),
        sa.Column("intent_payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("validation_result", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("execution_provenance", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("explainability", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("confidence_band", sa.Text(), nullable=True),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("queue_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("stream_entry_id", sa.Text(), nullable=True),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_intents_workspace_id", "intents", ["workspace_id"])
    op.create_index("ix_intents_network_id", "intents", ["network_id"])
    op.create_index("ix_intents_status", "intents", ["status"])
    op.create_index("ix_intents_requested_at", "intents", ["requested_at"])
    op.create_index("ix_intents_idempotency_key", "intents", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_intents_idempotency_key", table_name="intents")
    op.drop_index("ix_intents_requested_at", table_name="intents")
    op.drop_index("ix_intents_status", table_name="intents")
    op.drop_index("ix_intents_network_id", table_name="intents")
    op.drop_index("ix_intents_workspace_id", table_name="intents")
    op.drop_table("intents")
