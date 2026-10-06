"""ADR021 transactional Network inventory outbox.

DDL is explicit and frozen rather than derived from the evolving model (alembic/env.py
registers every model's metadata).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "network_outbox",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("network_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(128)),
        sa.CheckConstraint("attempts >= 0", name="ck_network_outbox_attempts"),
        sa.CheckConstraint("(lease_token IS NULL) = (lease_until IS NULL)", name="ck_network_outbox_lease"),
    )
    op.create_index(
        "ix_network_outbox_pending_network", "network_outbox", ["network_id", "sequence"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_index(
        "ix_network_outbox_due", "network_outbox", ["next_attempt_at", "sequence"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("network_outbox")
