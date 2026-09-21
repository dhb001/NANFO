"""Identity-owned durable audit event idempotency (ADR-010)."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical/direct auth rows remain untouched and may retain NULL identities.
    op.add_column("audit_logs", sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_unique_constraint("uq_audit_logs_event_id", "audit_logs", ["event_id"])


def downgrade() -> None:
    op.drop_constraint("uq_audit_logs_event_id", "audit_logs", type_="unique")
    op.drop_column("audit_logs", "event_id")
