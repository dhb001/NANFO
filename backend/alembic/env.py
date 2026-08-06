"""NANFO Backend — Alembic migration environment.

Uses a synchronous psycopg2 connection for migrations (Alembic requirement).
All module models are imported here so Alembic can detect schema changes.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all models to register metadata — must come before Base import
from app.modules.identity.models import User, Role, Permission, UserRole, AuditLog  # noqa: F401
from app.modules.organization.models import Organization, Workspace, OrgMember  # noqa: F401
from app.modules.network.models import Network, Device  # noqa: F401
from app.db.postgres import Base
from app.core.config import get_settings

config = context.config
settings = get_settings()

# Override sqlalchemy.url with the synchronous DSN from settings
config.set_main_option("sqlalchemy.url", settings.POSTGRES_SYNC_DSN)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
