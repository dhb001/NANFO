"""ADR023 durable calibrated provider state and exclusive autonomous lab recovery."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("autonomous_resources",
                    sa.Column("resource_id", sa.Text(), primary_key=True),
                    sa.Column("fence", sa.BigInteger(), nullable=False))
    op.create_table("autonomous_executions",
        sa.Column("execution_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("decision_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("network_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("fence", sa.BigInteger(), nullable=False),
        sa.Column("command", pg.JSONB(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("prepared", pg.JSONB()), sa.Column("result", pg.JSONB()),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("released", sa.Boolean(), nullable=False),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_until", sa.TIMESTAMP(timezone=True)),
        sa.Column("dispatched_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.CheckConstraint("fence > 0", name="ck_autonomous_fence"),
        sa.CheckConstraint("phase IN ('accepted','prepared','applying','verified','recovering','cancelled','uncertain')",
                           name="ck_autonomous_phase"),
        sa.CheckConstraint("NOT released OR phase = 'cancelled'", name="ck_autonomous_release"))
    op.create_index("uq_autonomous_resource_owned", "autonomous_executions", ["resource_id"], unique=True,
                    postgresql_where=sa.text("released = false"))
    op.create_index("uq_autonomous_decision", "autonomous_executions", ["decision_id"], unique=True)
    op.create_index("ix_autonomous_execution_pending", "autonomous_executions", ["updated_at"],
                    postgresql_where=sa.text("released = false"))
    op.create_table("autonomous_observations",
        sa.Column("observation_sha256", sa.Text(), primary_key=True),
        sa.Column("network_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("observation", pg.JSONB(), nullable=False),
        sa.Column("safety_observation", pg.JSONB(), nullable=False))
    op.create_table("autonomous_provider_state",
        sa.Column("network_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_sha256", sa.Text(), nullable=False),
        sa.Column("state", pg.JSONB(), nullable=False),
        sa.Column("evidence", pg.JSONB(), nullable=False))


def downgrade():
    # Execution journals, immutable measured frames and seeded provider history (ADR-028).
    if op.get_context().as_sql:
        raise RuntimeError("Downgrade below 0027 must run online (not --sql): it must first verify that "
                           "no autonomous journal or measured frame would be dropped")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM autonomous_executions) "
                                    "OR EXISTS (SELECT 1 FROM autonomous_observations) "
                                    "OR EXISTS (SELECT 1 FROM autonomous_provider_state)")):
        raise RuntimeError("Downgrade below 0027 refused: autonomous execution journals or measured frames exist")
    op.drop_table("autonomous_provider_state")
    op.drop_table("autonomous_observations")
    op.drop_table("autonomous_executions")
    op.drop_table("autonomous_resources")
