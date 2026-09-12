"""ADR-017 Simulation-owned model checkpoints, leases and lifecycle outbox.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("intent_executions", sa.Column("simulation_evidence", pg.JSONB(), nullable=True))
    op.execute("""
        CREATE FUNCTION preserve_execution_simulation_evidence() RETURNS trigger AS $$
        BEGIN
            IF NEW.simulation_evidence IS DISTINCT FROM OLD.simulation_evidence THEN
                RAISE EXCEPTION 'execution simulation evidence is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER preserve_execution_simulation_evidence
        BEFORE UPDATE OF simulation_evidence ON intent_executions
        FOR EACH ROW EXECUTE FUNCTION preserve_execution_simulation_evidence();
    """)
    for name in ("scenario_config", "checkpoint"):
        op.add_column("simulations", sa.Column(name, pg.JSONB(), nullable=True))
    op.add_column("simulations", sa.Column("input_sha256", sa.Text(), nullable=True))
    op.add_column(
        "simulations",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "simulations", sa.Column("lease_token", pg.UUID(as_uuid=True), nullable=True)
    )
    for name in ("lease_expires_at", "completed_at", "evidence_expires_at"):
        op.add_column(
            "simulations", sa.Column(name, sa.TIMESTAMP(timezone=True), nullable=True)
        )
    op.create_index(
        "ix_simulations_modeled_due",
        "simulations",
        ["state", "lease_expires_at"],
        postgresql_where=sa.text("scenario_config IS NOT NULL"),
    )
    op.create_table(
        "simulation_outbox",
        sa.Column("event_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "simulation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("simulations.simulation_id"),
            nullable=False,
        ),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("envelope", pg.JSONB(), nullable=False),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "simulation_id", "revision", name="uq_simulation_outbox_revision"
        ),
    )
    op.create_index(
        "ix_simulation_outbox_pending",
        "simulation_outbox",
        ["published_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade():
    op.execute("DROP TRIGGER preserve_execution_simulation_evidence ON intent_executions")
    op.execute("DROP FUNCTION preserve_execution_simulation_evidence()")
    op.drop_column("intent_executions", "simulation_evidence")
    op.drop_table("simulation_outbox")
    op.drop_index("ix_simulations_modeled_due", table_name="simulations")
    for name in (
        "evidence_expires_at",
        "completed_at",
        "lease_expires_at",
        "lease_token",
        "revision",
        "input_sha256",
        "checkpoint",
        "scenario_config",
    ):
        op.drop_column("simulations", name)
