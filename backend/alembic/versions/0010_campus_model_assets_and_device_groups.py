"""0010_campus_model_assets_and_device_groups - Network-owned model assets and device groups.

Adds persistence for campus model assets and native network-scoped device groups.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campus_model_assets",
        sa.Column("campus_model_asset_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("network_id", UUID(as_uuid=True), sa.ForeignKey("networks.network_id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_file_name", sa.Text(), nullable=False),
        sa.Column("model_mime_type", sa.Text(), nullable=False),
        sa.Column("model_data_base64", sa.Text(), nullable=False),
        sa.Column("model_sha256", sa.Text(), nullable=False),
        sa.Column("model_size_bytes", sa.Integer(), nullable=False),
        sa.Column("mapping_by_device_id", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_campus_model_assets_network_id", "campus_model_assets", ["network_id"])

    op.create_table(
        "device_groups",
        sa.Column("device_group_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("network_id", UUID(as_uuid=True), sa.ForeignKey("networks.network_id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("group_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("selector", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_device_groups_network_id", "device_groups", ["network_id"])
    op.create_index(
        "uq_device_groups_network_group_key_active",
        "device_groups",
        ["network_id", "group_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "device_group_members",
        sa.Column("device_group_member_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("device_group_id", UUID(as_uuid=True), sa.ForeignKey("device_groups.device_group_id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", UUID(as_uuid=True), sa.ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_device_group_members_group_id", "device_group_members", ["device_group_id"])
    op.create_index("ix_device_group_members_device_id", "device_group_members", ["device_id"])
    op.create_index(
        "uq_device_group_members_group_device_active",
        "device_group_members",
        ["device_group_id", "device_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_device_group_members_group_device_active", table_name="device_group_members")
    op.drop_index("ix_device_group_members_device_id", table_name="device_group_members")
    op.drop_index("ix_device_group_members_group_id", table_name="device_group_members")
    op.drop_table("device_group_members")

    op.drop_index("uq_device_groups_network_group_key_active", table_name="device_groups")
    op.drop_index("ix_device_groups_network_id", table_name="device_groups")
    op.drop_table("device_groups")

    op.drop_index("ix_campus_model_assets_network_id", table_name="campus_model_assets")
    op.drop_table("campus_model_assets")
