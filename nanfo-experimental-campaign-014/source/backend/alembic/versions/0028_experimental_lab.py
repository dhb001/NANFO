"""ADR025 separate experimental lab ownership, controls and immutable journal."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("experimental_lab_resources",
        sa.Column("resource_id", sa.Text(), primary_key=True),
        sa.Column("fence", sa.BigInteger(), nullable=False),
        sa.Column("owner_run_id", pg.UUID(as_uuid=True)))
    op.create_table("experimental_lab_runs",
        sa.Column("run_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("resource_id", sa.Text(), sa.ForeignKey("experimental_lab_resources.resource_id"), nullable=False),
        sa.Column("fence", sa.BigInteger(), nullable=False),
        sa.Column("policy", pg.JSONB(), nullable=False),
        sa.Column("policy_sha256", sa.Text(), nullable=False),
        sa.Column("stopped", sa.Boolean(), nullable=False),
        sa.Column("released", sa.Boolean(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_until", sa.TIMESTAMP(timezone=True)),
        sa.Column("action_count", sa.Integer(), nullable=False),
        sa.Column("last_dispatched_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("fence > 0 AND action_count >= 0", name="ck_experimental_run_bounds"))
    op.create_table("experimental_lab_actions",
        sa.Column("request_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("experimental_lab_runs.run_id"), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        *[sa.Column(name, pg.JSONB()) for name in ("command", "prepared", "frame", "inference", "simulation")],
        sa.Column("dispatched_at", sa.TIMESTAMP(timezone=True)))
    op.create_index("ix_experimental_lab_actions_run_id", "experimental_lab_actions", ["run_id"])
    op.create_index("uq_experimental_action_pending", "experimental_lab_actions", ["run_id"], unique=True,
                    postgresql_where=sa.text("phase NOT IN ('restored', 'rejected')"))
    op.create_table("experimental_lab_receipts",
        sa.Column("receipt_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("experimental_lab_runs.run_id"), nullable=False),
        sa.Column("request_id", pg.UUID(as_uuid=True), sa.ForeignKey("experimental_lab_actions.request_id")),
        sa.Column("kind", sa.Text(), nullable=False), sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False))
    op.create_index("ix_experimental_lab_receipts_run_id", "experimental_lab_receipts", ["run_id"])
    op.execute("""CREATE FUNCTION experimental_lab_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'experimental journal is immutable'; END $$""")
    op.execute("""CREATE TRIGGER experimental_receipt_immutable BEFORE UPDATE OR DELETE
        ON experimental_lab_receipts FOR EACH ROW EXECUTE FUNCTION experimental_lab_immutable()""")
    op.execute("""CREATE FUNCTION experimental_lab_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_TABLE_NAME = 'experimental_lab_runs' THEN
            IF OLD.policy IS DISTINCT FROM NEW.policy OR OLD.policy_sha256 <> NEW.policy_sha256
               OR OLD.run_id <> NEW.run_id OR OLD.resource_id <> NEW.resource_id OR OLD.fence <> NEW.fence
               OR (OLD.stopped AND NOT NEW.stopped) OR (OLD.released AND NOT NEW.released) THEN
              RAISE EXCEPTION 'experimental run binding is immutable';
            END IF;
          ELSE
            IF OLD.run_id <> NEW.run_id OR OLD.request_id <> NEW.request_id
               OR (OLD.command IS NOT NULL AND OLD.command IS DISTINCT FROM NEW.command)
               OR (OLD.prepared IS NOT NULL AND OLD.prepared IS DISTINCT FROM NEW.prepared)
               OR (OLD.frame IS NOT NULL AND OLD.frame IS DISTINCT FROM NEW.frame)
               OR (OLD.inference IS NOT NULL AND OLD.inference IS DISTINCT FROM NEW.inference)
               OR (OLD.simulation IS NOT NULL AND OLD.simulation IS DISTINCT FROM NEW.simulation) THEN
              RAISE EXCEPTION 'experimental action binding is immutable';
            END IF;
          END IF;
          RETURN NEW;
        END $$""")
    for table in ("runs", "actions"):
        op.execute(f"""CREATE TRIGGER experimental_{table}_binding BEFORE UPDATE ON experimental_lab_{table}
            FOR EACH ROW EXECUTE FUNCTION experimental_lab_binding_guard()""")


def downgrade():
    for table in ("receipts", "actions", "runs", "resources"):
        op.drop_table(f"experimental_lab_{table}")
    op.execute("DROP FUNCTION experimental_lab_binding_guard()")
    op.execute("DROP FUNCTION experimental_lab_immutable()")
