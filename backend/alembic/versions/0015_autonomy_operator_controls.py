"""ADR-018 Autonomy configuration and timed overrides ONLY. Model records use 0016.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("autonomy_configuration_revisions",
        sa.Column("network_id", pg.UUID(), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", pg.UUID(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("operational", pg.JSONB(), nullable=False),
        sa.Column("training", pg.JSONB(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("revision > 0", name="ck_autonomy_configuration_revision"))
    op.execute("""
        CREATE FUNCTION immutable_autonomy_configuration() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'configuration revisions are immutable'; END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER immutable_autonomy_configuration BEFORE UPDATE OR DELETE
        ON autonomy_configuration_revisions FOR EACH ROW EXECUTE FUNCTION immutable_autonomy_configuration();
    """)
    op.create_table("autonomy_overrides",
        sa.Column("override_id", pg.UUID(), primary_key=True),
        *[sa.Column(name, pg.UUID(), nullable=False) for name in
          ("network_id", "workspace_id", "intent_id", "execution_id", "run_id")],
        *[sa.Column(name, sa.Text(), nullable=False) for name in
          ("actor_id", "reason", "return_mode", "prior_mode", "command_sha256", "plan_hash", "binding_digest", "status")],
        *[sa.Column(name, sa.Integer(), nullable=False) for name in
          ("duration_seconds", "prior_revision", "hold_revision", "restoration_attempts")],
        *[sa.Column(name, sa.Text()) for name in
          ("checkpoint_sha256", "prior_approved_by_user_id", "cancelled_by_user_id", "return_requested_by_user_id", "return_reason")],
        sa.Column("recovery_reference", pg.JSONB(), nullable=False),
        sa.Column("reasons", pg.JSONB(), nullable=False),
        sa.Column("verification", pg.JSONB()),
        sa.Column("cancellation_id", pg.UUID()),
        sa.Column("claim_token", pg.UUID()),
        *[sa.Column(name, sa.TIMESTAMP(timezone=True)) for name in
          ("prior_approval_expires_at", "cancellation_requested_at", "restored_at", "return_requested_at", "returned_at", "lease_expires_at")],
        *[sa.Column(name, sa.TIMESTAMP(timezone=True), nullable=False) for name in
          ("configuration_verified_at", "expires_at", "next_check_at", "created_at", "updated_at")],
        sa.CheckConstraint("status IN ('holding', 'restoring', 'restored', 'return_blocked', 'returned')", name="ck_autonomy_override_status"),
        sa.CheckConstraint("duration_seconds BETWEEN 1 AND 3600", name="ck_autonomy_override_duration"),
        sa.CheckConstraint("return_mode IN ('monitor', 'recommend', 'autonomous') AND prior_mode IN ('monitor', 'recommend', 'autonomous')", name="ck_autonomy_override_modes"),
        sa.CheckConstraint("restoration_attempts >= 0 AND hold_revision > prior_revision", name="ck_autonomy_override_revision"))
    op.create_index("uq_autonomy_override_unresolved", "autonomy_overrides", ["network_id"], unique=True,
                    postgresql_where=sa.text("status IN ('holding', 'restoring')"))
    op.create_index("uq_autonomy_override_execution", "autonomy_overrides", ["execution_id"], unique=True)
    op.create_index("ix_autonomy_override_due", "autonomy_overrides", ["next_check_at", "lease_expires_at"],
                    postgresql_where=sa.text("status IN ('holding', 'restoring', 'restored')"))
    op.execute("""
        CREATE FUNCTION preserve_autonomy_override_enrollment() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['status','reasons','cancellation_id','cancellation_requested_at',
                'cancelled_by_user_id','restoration_attempts','verification','restored_at','return_requested_at',
                'return_requested_by_user_id','return_reason','returned_at','next_check_at','claim_token',
                'lease_expires_at','updated_at']) IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status','reasons','cancellation_id','cancellation_requested_at',
                'cancelled_by_user_id','restoration_attempts','verification','restored_at','return_requested_at',
                'return_requested_by_user_id','return_reason','returned_at','next_check_at','claim_token',
                'lease_expires_at','updated_at']) THEN
                RAISE EXCEPTION 'override enrollment is immutable';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER preserve_autonomy_override_enrollment BEFORE UPDATE ON autonomy_overrides
        FOR EACH ROW EXECUTE FUNCTION preserve_autonomy_override_enrollment();
    """)


def downgrade():
    op.drop_table("autonomy_overrides")
    op.execute("DROP FUNCTION preserve_autonomy_override_enrollment()")
    op.drop_table("autonomy_configuration_revisions")
    op.execute("DROP FUNCTION immutable_autonomy_configuration()")
