"""ADR-021 Network-owned canonical spatial scene after inventory outbox."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    # Frozen DDL; alembic/env.py registers the owning model metadata.
    op.create_table(
        "network_spatial_scenes",
        sa.Column("network_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("networks.network_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("scene", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("revision >= 0 AND revision <= 9007199254740991", name="ck_spatial_scene_revision"),
    )


def downgrade():
    op.drop_table("network_spatial_scenes")
