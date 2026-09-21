"""0004_simulation_lifecycle_baseline - Simulation persistence baseline for VS7 Step 1.

Creates simulations table for lifecycle state, validation metadata,
run outputs, model versions, and audit provenance.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulations",
        sa.Column("simulation_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("parent_simulation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("network_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_name", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("risk_gate", sa.Text(), nullable=False),
        sa.Column("validation", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("run_output", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("model_versions", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("audit_provenance", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("queue_status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("stream_entry_id", sa.Text(), nullable=True),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["parent_simulation_id"], ["simulations.simulation_id"], ondelete="SET NULL"),
    )

    op.create_index("ix_simulations_network_id", "simulations", ["network_id"])
    op.create_index("ix_simulations_workspace_id", "simulations", ["workspace_id"])
    op.create_index("ix_simulations_scenario_id", "simulations", ["scenario_id"])
    op.create_index("ix_simulations_parent_simulation_id", "simulations", ["parent_simulation_id"])
    op.create_index("ix_simulations_state", "simulations", ["state"])


def downgrade() -> None:
    op.drop_index("ix_simulations_state", table_name="simulations")
    op.drop_index("ix_simulations_parent_simulation_id", table_name="simulations")
    op.drop_index("ix_simulations_scenario_id", table_name="simulations")
    op.drop_index("ix_simulations_workspace_id", table_name="simulations")
    op.drop_index("ix_simulations_network_id", table_name="simulations")
    op.drop_table("simulations")
