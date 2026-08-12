"""0003_device_spatial_ref — Device spatial reference baseline for VS6 Step 1.

Adds optional spatial_ref_id to devices for Digital Twin spatial synchronization.
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("spatial_ref_id", sa.Text(), nullable=True))
    op.create_index("ix_devices_spatial_ref_id", "devices", ["spatial_ref_id"])


def downgrade() -> None:
    op.drop_index("ix_devices_spatial_ref_id", table_name="devices")
    op.drop_column("devices", "spatial_ref_id")
