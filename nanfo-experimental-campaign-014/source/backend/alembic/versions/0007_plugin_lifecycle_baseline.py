"""0007_plugin_lifecycle_baseline - Plugin registry baseline for VS12 Step 1.

Creates plugins table for install/enable/disable lifecycle and safety metadata.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugins",
        sa.Column("plugin_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("plugin_key", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("manifest", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("signature_status", sa.Text(), nullable=False, server_default=sa.text("'unverified'")),
        sa.Column("dependency_status", sa.Text(), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column("sandbox_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'installed'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("queue_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("stream_entry_id", sa.Text(), nullable=True),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("installed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_plugins_status", "plugins", ["status"])
    op.create_index("ix_plugins_enabled", "plugins", ["enabled"])
    op.create_index("ix_plugins_installed_at", "plugins", ["installed_at"])


def downgrade() -> None:
    op.drop_index("ix_plugins_installed_at", table_name="plugins")
    op.drop_index("ix_plugins_enabled", table_name="plugins")
    op.drop_index("ix_plugins_status", table_name="plugins")
    op.drop_table("plugins")
