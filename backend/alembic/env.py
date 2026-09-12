"""NANFO Backend — Alembic migration environment.

Uses a synchronous psycopg2 connection for migrations (Alembic requirement).
All module models are imported here so Alembic can detect schema changes.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.db.postgres import Base
from app.modules.alert.models import AlertRecord  # noqa: F401
from app.modules.autonomy.model_diagnostic_models import ModelDiagnostic  # noqa: F401
from app.modules.autonomy.models import AutonomyControl, AutonomyDecision  # noqa: F401

# Import all models to register metadata — must come before Base import
from app.modules.identity.models import (  # noqa: F401
    AuditLog,
    Permission,
    Role,
    User,
    UserRole,
)
from app.modules.intent.models import (  # noqa: F401
    Intent,
    IntentExecution,
    IntentOutbox,
)
from app.modules.network.models import (  # noqa: F401
    CampusBuildingRecord,
    Device,
    Network,
)
from app.modules.organization.models import (  # noqa: F401
    Organization,
    OrgMember,
    Workspace,
)
from app.modules.plugin.models import PluginRecord  # noqa: F401
from app.modules.report.models import ReportRecord  # noqa: F401
from app.modules.simulation.models import Simulation, SimulationOutbox  # noqa: F401
from app.modules.telemetry.models import TelemetryRecord  # noqa: F401

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
