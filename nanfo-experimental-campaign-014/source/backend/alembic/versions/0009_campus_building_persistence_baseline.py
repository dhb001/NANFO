"""0009_campus_building_persistence_baseline - Campus building persistence baseline.

Adds network-owned campus_buildings table for persisted Digital Twin building geometry.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campus_buildings",
        sa.Column("campus_building_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("network_id", UUID(as_uuid=True), sa.ForeignKey("networks.network_id", ondelete="CASCADE"), nullable=False),
        sa.Column("building_id", sa.Text(), nullable=False),
        sa.Column("campus_key", sa.Text(), nullable=False),
        sa.Column("building_key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("geometry", sa.Text(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("z", sa.Float(), nullable=False),
        sa.Column("base_y", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("depth", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("floors", sa.Integer(), nullable=False),
        sa.Column("footprint", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("wall_material", sa.Text(), nullable=True),
        sa.Column("attenuation_db", sa.Float(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_index("ix_campus_buildings_network_id", "campus_buildings", ["network_id"])
    op.create_index("ix_campus_buildings_building_id", "campus_buildings", ["building_id"])


def downgrade() -> None:
    op.drop_index("ix_campus_buildings_building_id", table_name="campus_buildings")
    op.drop_index("ix_campus_buildings_network_id", table_name="campus_buildings")
    op.drop_table("campus_buildings")
