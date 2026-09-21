"""Invalidate old Autonomy coverage for complete experimental0028 history scanning."""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def invalidate():
    # Metadata only. Existing pins, journals, telemetry and other owners are retained.
    # Serialize with active retention/reconciliation before changing coverage claims.
    op.execute("LOCK TABLE telemetry_reference_reconciliation, telemetry_reference_coverage IN EXCLUSIVE MODE")
    op.execute("""UPDATE telemetry_reference_coverage SET revoked_at = clock_timestamp()
                  WHERE owner = 'autonomy'""")
    op.execute("""UPDATE telemetry_reference_reconciliation
                  SET cursor = NULL, complete = false, scanned = 0, unknown = 0,
                      started_at = clock_timestamp()
                  WHERE owner = 'autonomy'""")


def upgrade():
    invalidate()


def downgrade():
    # Never resurrect an older completeness claim on rollback. Re-enrollment must
    # follow a real scan under the installed owner's enumeration implementation.
    invalidate()
