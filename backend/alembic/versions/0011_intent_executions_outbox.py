"""0011: Intent-owned durable manual lab execution and immutable event outbox."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intent_executions",
        sa.Column("execution_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("intent_id", UUID(as_uuid=True), sa.ForeignKey("intents.intent_id"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("lab_key", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("command", JSONB(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("blocks_lab", sa.Boolean(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("cancelled_by_user_id", sa.Text()),
        sa.Column("cancellation_requested_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("outbox_sequence", sa.Integer(), nullable=False),
        sa.Column("dispatched_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("result", JSONB()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_until", sa.TIMESTAMP(timezone=True)),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("intent_id", name="uq_intent_executions_intent"),
        sa.UniqueConstraint("workspace_id", "request_key", name="uq_intent_executions_request"),
        sa.CheckConstraint("fence >= 0", name="ck_intent_executions_fence"),
    )
    op.create_index("uq_intent_executions_blocking_lab", "intent_executions", ["lab_key"],
                    unique=True, postgresql_where=sa.text("blocks_lab"))
    op.create_table(
        "intent_outbox",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("execution_id", UUID(as_uuid=True), sa.ForeignKey("intent_executions.execution_id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("envelope", JSONB(), nullable=False),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("lease_owner", sa.Text()),
        sa.Column("lease_until", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("execution_id", "sequence", name="uq_intent_outbox_sequence"),
    )
    op.create_index("ix_intent_outbox_pending", "intent_outbox", ["created_at"],
                    postgresql_where=sa.text("published_at IS NULL"))


def downgrade() -> None:
    op.drop_table("intent_outbox")
    op.drop_table("intent_executions")
