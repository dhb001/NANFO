"""ADR019 metadata registry soft-uninstall; preserve historical declarations."""

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plugins", sa.Column("uninstalled_at", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("plugins", "uninstalled_at")
