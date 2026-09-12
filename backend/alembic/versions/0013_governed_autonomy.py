"""Autonomy-owned controls and decision journal (ADR-012)."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("autonomy_controls",
        sa.Column("network_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("checkpoint_sha256", sa.Text()),
        sa.Column("approval_expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("approved_by_user_id", sa.Text()),
        sa.Column("emergency_stopped", sa.Boolean(), nullable=False),
        sa.Column("stopped_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("stopped_by_user_id", sa.Text()),
        sa.Column("active_execution_id", pg.UUID(as_uuid=True)),
        sa.Column("active_intent_id", pg.UUID(as_uuid=True)),
        sa.Column("active_decision_id", pg.UUID(as_uuid=True)),
        sa.Column("cancellation_status", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("claim_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("next_cycle_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_observation", pg.JSONB()),
        sa.Column("last_accepted_observed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("mode IN ('monitor', 'recommend', 'autonomous')", name="ck_autonomy_mode"),
        sa.CheckConstraint("cancellation_status IN ('none', 'requested', 'verified', 'uncertain')",
                           name="ck_autonomy_cancellation_status"),
        sa.CheckConstraint("revision >= 0", name="ck_autonomy_revision"),
        sa.CheckConstraint("(active_execution_id IS NULL AND active_intent_id IS NULL AND active_decision_id IS NULL) "
                           "OR (active_execution_id IS NOT NULL AND active_intent_id IS NOT NULL AND active_decision_id IS NOT NULL)",
                           name="ck_autonomy_execution_identity"),
    )
    op.create_index("ix_autonomy_controls_due", "autonomy_controls", ["next_cycle_at", "network_id"],
                    postgresql_where=sa.text("(approved_by_user_id IS NOT NULL OR active_execution_id IS NOT NULL) AND (NOT emergency_stopped OR active_execution_id IS NOT NULL)"))
    op.create_index("uq_autonomy_controls_execution", "autonomy_controls", ["active_execution_id"], unique=True)
    op.create_table("autonomy_decisions",
        sa.Column("decision_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("network_id", pg.UUID(as_uuid=True), sa.ForeignKey("autonomy_controls.network_id"), nullable=False),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("control_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reasons", pg.JSONB(), nullable=False),
        sa.Column("checkpoint_sha256", sa.Text()),
        sa.Column("observation", pg.JSONB()),
        sa.Column("proposal", pg.JSONB()),
        sa.Column("safety", pg.JSONB()),
        sa.Column("evidence", pg.JSONB(), nullable=False),
        sa.Column("execution_id", pg.UUID(as_uuid=True)),
        sa.Column("verification", pg.JSONB()),
        sa.Column("authorization", pg.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_autonomy_decisions_network_created", "autonomy_decisions", ["network_id", "created_at", "decision_id"])
    op.create_index("ix_autonomy_decisions_observing", "autonomy_decisions", ["network_id"],
                    postgresql_where=sa.text("status = 'observing'"))


def downgrade():
    op.drop_index("ix_autonomy_decisions_observing", table_name="autonomy_decisions")
    op.drop_index("ix_autonomy_decisions_network_created", table_name="autonomy_decisions")
    op.drop_table("autonomy_decisions")
    op.drop_index("uq_autonomy_controls_execution", table_name="autonomy_controls")
    op.drop_index("ix_autonomy_controls_due", table_name="autonomy_controls")
    op.drop_table("autonomy_controls")
