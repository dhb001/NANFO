"""ADR018 isolated model diagnostics after the operator configuration migration."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("autonomy_model_diagnostics",
        sa.Column("diagnostic_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("network_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_model_diagnostics_scope_created", "autonomy_model_diagnostics",
                    ["network_id", "workspace_id", "created_at", "diagnostic_id"])
    op.execute("""CREATE FUNCTION reject_model_diagnostic_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'model diagnostics are immutable'; END $$""")
    op.execute("""CREATE TRIGGER model_diagnostic_immutable BEFORE UPDATE OR DELETE
        ON autonomy_model_diagnostics FOR EACH ROW EXECUTE FUNCTION reject_model_diagnostic_mutation()""")


def downgrade():
    op.drop_table("autonomy_model_diagnostics")
    op.execute("DROP FUNCTION reject_model_diagnostic_mutation()")
