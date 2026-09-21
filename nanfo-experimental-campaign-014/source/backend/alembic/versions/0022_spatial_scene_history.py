"""ADR-022 immutable spatial bodies; asset registration belongs to0023."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op
from app.modules.network.spatial_models import SpatialSceneRevision  # noqa: F401 -- owning metadata

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    # Baseline is copied under a write barrier; deploy with old scene writers drained.
    op.execute("LOCK TABLE network_spatial_scenes IN SHARE MODE")
    op.create_table(
        "network_spatial_scene_revisions",
        sa.Column("network_id", pg.UUID(as_uuid=True), sa.ForeignKey("networks.network_id"), primary_key=True),
        sa.Column("revision", sa.BigInteger(), primary_key=True),
        sa.Column("scene", pg.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.CheckConstraint("revision >= 0 AND revision <= 9007199254740991", name="ck_spatial_history_revision"),
        sa.CheckConstraint("origin IN ('baseline', 'replacement')", name="ck_spatial_history_origin"),
        sa.CheckConstraint("origin = 'baseline' OR actor_id IS NOT NULL", name="ck_spatial_history_actor"),
    )
    # Preserve the body we actually have. Earlier audit hashes cannot recover history.
    op.execute("""INSERT INTO network_spatial_scene_revisions(network_id, revision, scene, origin)
        SELECT network_id, revision, scene, 'baseline' FROM network_spatial_scenes""")
    op.execute("""CREATE FUNCTION protect_spatial_scene_history() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'spatial scene history is immutable';
        END $$""")
    op.execute("""CREATE TRIGGER spatial_scene_history_immutable
        BEFORE UPDATE OR DELETE ON network_spatial_scene_revisions
        FOR EACH ROW EXECUTE FUNCTION protect_spatial_scene_history()""")
    op.execute("""CREATE TRIGGER spatial_scene_history_no_truncate
        BEFORE TRUNCATE ON network_spatial_scene_revisions
        FOR EACH STATEMENT EXECUTE FUNCTION protect_spatial_scene_history()""")


def downgrade():
    op.drop_table("network_spatial_scene_revisions")
    op.execute("DROP FUNCTION protect_spatial_scene_history()")
