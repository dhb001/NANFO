"""0001_initial_schema — Initial NANFO schema for Vertical Slice 1.

Creates all tables owned by Identity, Organization, and Network modules.
Module ownership per ADR-004 and design_package_vertical_slice_1.md §5.

Cross-module references are stored as UUID columns (NOT SQL foreign keys)
to enforce module boundary separation. Reference integrity is enforced
at the service layer only (ADR-004; database.md §2).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Identity Module ───────────────────────────────────────────────────────

    op.create_table(
        "roles",
        sa.Column("role_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
    )
    op.execute("INSERT INTO roles (name) VALUES ('Admin'), ('Operator'), ('Read-Only')")

    op.create_table(
        "permissions",
        sa.Column("permission_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
    )
    op.execute(
        "INSERT INTO permissions (name) VALUES "
        "('write:config'), ('execute:rollback'), ('read:topology'), ('read:telemetry'), ('manage:users'), ('manage:orgs')"
    )

    op.create_table(
        "users",
        sa.Column("user_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "user_roles",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.role_id", ondelete="CASCADE"), primary_key=True),
    )

    # audit_logs: immutable append-only (Authentication.md §4)
    # No UPDATE or DELETE ever executed against this table.
    op.create_table(
        "audit_logs",
        sa.Column("log_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("resource_type", sa.Text(), nullable=True),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        sa.Column("org_id", UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("metadata", JSONB(), nullable=True),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])

    # ── Organization Module ───────────────────────────────────────────────────

    op.create_table(
        "organizations",
        sa.Column("org_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    op.create_table(
        "workspaces",
        # org_id FK is within-module: Organization owns both tables
        sa.Column("workspace_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_workspaces_org_id", "workspaces", ["org_id"])

    op.create_table(
        "org_members",
        # user_id is a logical reference — NO SQL FK to identity.users (ADR-004)
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.org_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, primary_key=True),  # logical ref to Identity
        sa.Column("org_role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_org_members_user_id", "org_members", ["user_id"])

    # ── Network Module ────────────────────────────────────────────────────────

    op.create_table(
        "networks",
        # workspace_id is a logical reference — NO SQL FK to org.workspaces (ADR-004)
        sa.Column("network_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),  # logical ref to Organization
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cidr", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_networks_workspace_id", "networks", ["workspace_id"])

    op.create_table(
        "devices",
        # network_id FK is within-module: Network owns both tables
        sa.Column("device_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("network_id", UUID(as_uuid=True), sa.ForeignKey("networks.network_id", ondelete="CASCADE"), nullable=False),
        sa.Column("hostname", sa.Text(), nullable=False),
        sa.Column("ip_address", INET(), nullable=True),
        sa.Column("device_type", sa.Text(), nullable=False),
        sa.Column("vendor", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        # location_hint is intentionally ephemeral free text (design_package §5.3 note: will be
        # superseded by spatial_ref_id (UOM reference) in M6 Digital Twin slice)
        sa.Column("location_hint", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="'active'"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_devices_network_id", "devices", ["network_id"])
    op.create_index("ix_devices_hostname", "devices", ["hostname"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("devices")
    op.drop_table("networks")
    op.drop_table("org_members")
    op.drop_table("workspaces")
    op.drop_table("organizations")
    op.drop_table("audit_logs")
    op.drop_table("user_roles")
    op.drop_table("users")
    op.drop_table("permissions")
    op.drop_table("roles")
