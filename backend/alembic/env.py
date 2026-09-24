"""NANFO Backend — Alembic migration environment.

Uses a synchronous psycopg2 connection for migrations (Alembic requirement); the DSN
always comes from environment-backed settings (``POSTGRES_SYNC_DSN``), never alembic.ini.

* Every model module is imported below so autogenerate / ``alembic check`` compare the
  complete metadata, including types and server defaults (the list is enforced by
  tests/unit/test_model_migration_parity.py).
* Each revision runs in its own transaction (``transaction_per_migration``), which is
  required by revisions with an autocommit block (``CREATE INDEX CONCURRENTLY``).
* ``lock_timeout`` (``NANFO_MIGRATION_LOCK_TIMEOUT``, default ``5s``; ``0`` disables)
  makes DDL fail fast instead of queueing application traffic behind a blocked lock.
* A caller may pass an open connection as ``config.attributes["connection"]`` (for
  example tests running against a disposable schema); it is used as-is.
"""

import os
import re
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from app.core.config import get_settings
from app.db.postgres import Base

# Import every model module to register its metadata.
from app.modules.alert import models as alert_models  # noqa: F401
from app.modules.autonomy import execution_models  # noqa: F401
from app.modules.autonomy import model_diagnostic_models  # noqa: F401
from app.modules.autonomy import models as autonomy_models  # noqa: F401
from app.modules.autonomy.experimental import models as experimental_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.intent import models as intent_models  # noqa: F401
from app.modules.network import models as network_models  # noqa: F401
from app.modules.network import outbox_models, spatial_models  # noqa: F401
from app.modules.organization import models as organization_models  # noqa: F401
from app.modules.plugin import models as plugin_models  # noqa: F401
from app.modules.report import models as report_models  # noqa: F401
from app.modules.simulation import models as simulation_models  # noqa: F401
from app.modules.telemetry import archive_models, fleet_models, pin_models  # noqa: F401
from app.modules.telemetry import models as telemetry_models  # noqa: F401

LOCK_TIMEOUT_SETTING = "NANFO_MIGRATION_LOCK_TIMEOUT"
DEFAULT_LOCK_TIMEOUT = "5s"
_DURATION = re.compile(r"\d+(\.\d+)?\s*(us|ms|s|min|h|d)?")

config = context.config
settings = get_settings()

# Override sqlalchemy.url with the synchronous DSN from settings
config.set_main_option("sqlalchemy.url", settings.POSTGRES_SYNC_DSN.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
MIGRATION_OPTIONS = {"compare_type": True, "compare_server_default": True, "transaction_per_migration": True}


def lock_timeout() -> str:
    """Validated PostgreSQL duration (it is also rendered literally into offline SQL)."""
    configured = getattr(settings, LOCK_TIMEOUT_SETTING, None) or os.environ.get(LOCK_TIMEOUT_SETTING)
    value = str(configured or DEFAULT_LOCK_TIMEOUT).strip()
    if not _DURATION.fullmatch(value):
        raise RuntimeError(f"{LOCK_TIMEOUT_SETTING} must be a PostgreSQL duration such as 5s, 500ms or 0")
    return value


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **MIGRATION_OPTIONS,
    )
    with context.begin_transaction():
        context.execute(f"SET lock_timeout = '{lock_timeout()}'")
        context.run_migrations()


def _run_on(connection) -> None:
    # A caller-owned transaction keeps its scope; otherwise set it for the session and
    # commit so each revision starts its own transaction.
    external = connection.in_transaction()
    connection.execute(text("SELECT set_config('lock_timeout', :value, :local)"),
                       {"value": lock_timeout(), "local": external})
    if not external:
        connection.commit()
    context.configure(connection=connection, target_metadata=target_metadata, **MIGRATION_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied = config.attributes.get("connection")
    if supplied is not None:
        _run_on(supplied)
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run_on(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
