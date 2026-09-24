"""ADR019 Alert-owned measured detector, immutable history and lifecycle outbox."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("alerts", sa.Column("detector_key", sa.Text(), nullable=True))
    op.create_index("uq_alert_measured_incident", "alerts", ["detector_key"], unique=True,
                    postgresql_where=sa.text("detector_key IS NOT NULL AND status != 'resolved'"))
    op.create_table("alert_detector_states",
        sa.Column("detector_key", sa.Text(), primary_key=True),
        sa.Column("identity", pg.JSONB(), nullable=False),
        sa.Column("rule", pg.JSONB(), nullable=False),
        sa.Column("last_observed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_event_id", pg.UUID(as_uuid=True)),
        sa.Column("phase", sa.Text()),
        sa.Column("phase_since", sa.TIMESTAMP(timezone=True)),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("incident_id", pg.UUID(as_uuid=True), sa.ForeignKey("alerts.alert_id")),
    )
    op.create_table("alert_observations",
        sa.Column("event_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("detector_key", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_table("alert_consumed_events",
        sa.Column("event_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("payload_sha256", sa.Text(), nullable=False),
        sa.Column("alert_id", pg.UUID(as_uuid=True), sa.ForeignKey("alerts.alert_id")),
        sa.Column("consumed_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table("alert_history",
        sa.Column("event_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_id", pg.UUID(as_uuid=True), sa.ForeignKey("alerts.alert_id"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("correlation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
    )
    op.create_index("ix_alert_history_incident", "alert_history", ["alert_id", "occurred_at", "event_id"])
    op.create_table("alert_outbox",
        sa.Column("event_id", pg.UUID(as_uuid=True), sa.ForeignKey("alert_history.event_id"), primary_key=True),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_alert_outbox_pending", "alert_outbox", ["published_at"])
    op.execute("""CREATE FUNCTION reject_alert_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'alert history is immutable'; END $$""")
    op.execute("""CREATE TRIGGER alert_history_immutable BEFORE UPDATE OR DELETE
        ON alert_history FOR EACH ROW EXECUTE FUNCTION reject_alert_history_mutation()""")


def downgrade():
    # alert_history is the immutable (trigger-protected) lifecycle journal (ADR-028).
    if op.get_context().as_sql:
        raise RuntimeError("Downgrade below 0018 must run online (not --sql): it must first verify that "
                           "no immutable alert history would be dropped")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM alert_history)")):
        raise RuntimeError("Downgrade below 0018 refused: immutable alert history exists")
    op.drop_table("alert_consumed_events")
    op.drop_table("alert_outbox")
    op.drop_table("alert_history")
    op.execute("DROP FUNCTION reject_alert_history_mutation()")
    op.drop_table("alert_observations")
    op.drop_table("alert_detector_states")
    op.drop_index("uq_alert_measured_incident", table_name="alerts")
    op.drop_column("alerts", "detector_key")
