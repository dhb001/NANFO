"""Network protected asset storage and explicit nullable registration.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("campus_model_assets", sa.Column("registration", postgresql.JSONB(), nullable=True))
    op.add_column("campus_model_assets", sa.Column("storage_backend", sa.Text(), nullable=False, server_default="inline"))
    op.alter_column("campus_model_assets", "model_data_base64", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint("ck_campus_asset_storage", "campus_model_assets", """
        (storage_backend = 'inline' AND model_data_base64 IS NOT NULL)
        OR (storage_backend = 'local_cas' AND model_data_base64 IS NULL
            AND model_sha256 ~ '^[0-9a-f]{64}$' AND model_size_bytes BETWEEN 1 AND 8388608)
    """)
    op.execute("""
        CREATE FUNCTION network_asset_identity_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.campus_model_asset_id IS DISTINCT FROM OLD.campus_model_asset_id
             OR NEW.network_id IS DISTINCT FROM OLD.network_id
             OR NEW.model_sha256 IS DISTINCT FROM OLD.model_sha256
             OR NEW.model_size_bytes IS DISTINCT FROM OLD.model_size_bytes THEN
            RAISE EXCEPTION 'campus asset content identity is immutable';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER campus_asset_identity_immutable BEFORE UPDATE ON campus_model_assets
        FOR EACH ROW EXECUTE FUNCTION network_asset_identity_immutable()
    """)


def downgrade():
    # Frozen SQL guard runs for offline-generated migrations too. Never discard CAS references.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM campus_model_assets WHERE storage_backend <> 'inline'
                     OR model_data_base64 IS NULL) THEN
            RAISE EXCEPTION 'Restore every asset inline using the asset backfill CLI before downgrade';
          END IF;
        END $$
    """)
    op.execute("DROP TRIGGER campus_asset_identity_immutable ON campus_model_assets")
    op.execute("DROP FUNCTION network_asset_identity_immutable()")
    op.drop_constraint("ck_campus_asset_storage", "campus_model_assets", type_="check")
    op.alter_column("campus_model_assets", "model_data_base64", existing_type=sa.Text(), nullable=False)
    op.drop_column("campus_model_assets", "storage_backend")
    op.drop_column("campus_model_assets", "registration")
