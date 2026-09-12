"""ADR019 durable report snapshots, worker fencing and lifecycle outbox."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("artifact_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot", pg.JSONB()),
        sa.Column("snapshot_sha256", sa.Text()),
        sa.Column("receipt", pg.JSONB()),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.TIMESTAMP(timezone=True)),
    ):
        op.add_column("reports", column)
    # No source cursor/snapshot exists for pre-0017 jobs. Never render invented history.
    op.execute("""UPDATE reports SET status='failed', artifact_refs='[]'::jsonb,
        error_context='{"code":"REPORT_LEGACY_SNAPSHOT_UNAVAILABLE","message":"Historical report has no frozen source snapshot; submit a new request."}'::jsonb,
        completed_at=COALESCE(completed_at, now()) WHERE status NOT IN ('generated','failed')""")
    op.create_table(
        "report_outbox",
        sa.Column("event_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("status_version", sa.Integer(), nullable=False),
        sa.Column("envelope", pg.JSONB(), nullable=False),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("stream_entry_id", sa.Text()),
        sa.UniqueConstraint(
            "report_id", "status_version", name="uq_report_outbox_version"
        ),
    )
    op.create_index(
        "ix_reports_history",
        "reports",
        ["workspace_id", "requested_by_user_id", "requested_at", "report_id"],
    )
    op.create_index("ix_reports_worker", "reports", ["status", "lease_expires_at"])
    op.create_index("ix_report_outbox_pending", "report_outbox", ["published_at"])
    op.execute("""CREATE FUNCTION protect_report_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.artifact_version = 1 AND
            (NEW.snapshot IS DISTINCT FROM OLD.snapshot OR NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256
             OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id OR NEW.requested_by_user_id IS DISTINCT FROM OLD.requested_by_user_id
             OR NEW.network_id IS DISTINCT FROM OLD.network_id OR NEW.date_range IS DISTINCT FROM OLD.date_range
             OR NEW.scope IS DISTINCT FROM OLD.scope OR NEW.filters IS DISTINCT FROM OLD.filters
             OR NEW.report_type IS DISTINCT FROM OLD.report_type OR NEW.output_format IS DISTINCT FROM OLD.output_format
             OR NEW.artifact_version IS DISTINCT FROM OLD.artifact_version)
          THEN RAISE EXCEPTION 'report snapshot is immutable'; END IF;
          RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER report_snapshot_immutable BEFORE UPDATE ON reports FOR EACH ROW EXECUTE FUNCTION protect_report_snapshot()"
    )


def downgrade():
    op.execute("DROP TRIGGER report_snapshot_immutable ON reports")
    op.execute("DROP FUNCTION protect_report_snapshot()")
    op.drop_table("report_outbox")
    op.drop_index("ix_reports_history", table_name="reports")
    op.drop_index("ix_reports_worker", table_name="reports")
    for name in (
        "lease_expires_at",
        "lease_token",
        "receipt",
        "snapshot_sha256",
        "snapshot",
        "status_version",
        "artifact_version",
    ):
        op.drop_column("reports", name)
