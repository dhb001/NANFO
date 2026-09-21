"""Fresh deployment only: provision separate roles, migrate as owner, seed Identity."""

import asyncio
import os
import subprocess
from pathlib import Path

import psycopg2
from psycopg2 import sql

from deploy.entrypoint import read_secret


async def seed_actor():
    from app.core.security import hash_password
    from app.db.postgres import AsyncSessionLocal, get_engine
    from app.modules.identity.repository import UserRepository

    async with AsyncSessionLocal() as session:
        repository = UserRepository(session)
        email = os.environ["NANFO_BOOTSTRAP_EMAIL"]
        if await repository.get_by_email(email):
            raise ValueError("Bootstrap actor already exists")
        password = read_secret(Path("/run/secrets/bootstrap_password"))
        user = await repository.create(
            email, hash_password(password), "Deployment Operator"
        )
        await repository.assign_role(user.user_id, "Admin")
        await session.commit()
    await get_engine().dispose()


def main():
    owner_password = read_secret(Path("/run/secrets/postgres_owner_password"))
    connection = psycopg2.connect(
        host="postgres",
        dbname="nanfo",
        user="postgres",
        password=read_secret(Path("/run/secrets/postgres_admin_password")),
        connect_timeout=10,
    )
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        if cursor.fetchone()[0]:
            raise ValueError("Existing database: implicit migration/upgrade forbidden")
        for role, password in (
            ("nanfo_owner", owner_password),
            ("nanfo_runtime", os.environ["POSTGRES_PASSWORD"]),
        ):
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
        cursor.execute("ALTER DATABASE nanfo OWNER TO nanfo_owner")
        cursor.execute("REVOKE ALL ON DATABASE nanfo FROM PUBLIC")
        cursor.execute("GRANT CONNECT ON DATABASE nanfo TO nanfo_runtime")
        cursor.execute("ALTER SCHEMA public OWNER TO nanfo_owner")
        cursor.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    connection.close()
    os.environ.update(POSTGRES_USER="nanfo_owner", POSTGRES_PASSWORD=owner_password)
    from app.core.schema_version import CURRENT_SCHEMA

    subprocess.run(["alembic", "upgrade", CURRENT_SCHEMA], check=True)
    connection = psycopg2.connect(
        host="postgres", dbname="nanfo", user="nanfo_owner", password=owner_password
    )
    with connection, connection.cursor() as cursor:
        cursor.execute("GRANT USAGE ON SCHEMA public TO nanfo_runtime")
        cursor.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nanfo_runtime"
        )
        cursor.execute(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nanfo_runtime"
        )
        cursor.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC")
        cursor.execute(
            "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO nanfo_runtime"
        )
        cursor.execute(
            "REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM nanfo_runtime"
        )
        cursor.execute("REVOKE UPDATE, DELETE ON audit_logs FROM nanfo_runtime")
        cursor.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nanfo_runtime"
        )
        cursor.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO nanfo_runtime"
        )
        cursor.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
        )
        cursor.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO nanfo_runtime"
        )
        # Check the new writer tables and identity sequence after migrations/grants.
        # This is role metadata inspection, not an application-domain write.
        cursor.execute(
            "SELECT "
            "has_table_privilege('nanfo_runtime', 'network_outbox', 'SELECT') AND "
            "has_table_privilege('nanfo_runtime', 'network_outbox', 'INSERT') AND "
            "has_table_privilege('nanfo_runtime', 'network_outbox', 'UPDATE') AND "
            "has_table_privilege('nanfo_runtime', 'network_outbox', 'DELETE') AND "
            "has_table_privilege('nanfo_runtime', 'network_spatial_scenes', 'SELECT') AND "
            "has_table_privilege('nanfo_runtime', 'network_spatial_scenes', 'INSERT') AND "
            "has_table_privilege('nanfo_runtime', 'network_spatial_scenes', 'UPDATE') AND "
            "has_table_privilege('nanfo_runtime', 'network_spatial_scenes', 'DELETE') AND "
            "has_sequence_privilege('nanfo_runtime', "
            "pg_get_serial_sequence('network_outbox', 'sequence'), 'USAGE') AND "
            "has_sequence_privilege('nanfo_runtime', "
            "pg_get_serial_sequence('network_outbox', 'sequence'), 'SELECT')"
        )
        if cursor.fetchone()[0] is not True:
            raise ValueError("Network runtime table/identity privileges unavailable")
        for table in (
            "network_spatial_scene_revisions",
            "campus_model_assets",
            "telemetry_evidence_pins",
            "telemetry_reference_coverage",
            "telemetry_event_tombstones",
            "telemetry_archive_receipts",
            "telemetry_reference_reconciliation",
            "telemetry_fleet_devices",
            "telemetry_fleet_spool",
            "autonomous_resources",
            "autonomous_executions",
            "autonomous_observations",
            "autonomous_provider_state",
            "experimental_lab_resources",
            "experimental_lab_runs",
            "experimental_lab_actions",
            "experimental_lab_receipts",
        ):
            cursor.execute(
                "SELECT bool_and(has_table_privilege('nanfo_runtime', %s, privilege)) "
                "FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) AS privilege",
                (table,),
            )
            if cursor.fetchone()[0] is not True:
                raise ValueError("ADR022/023 runtime table privileges unavailable")
    connection.close()
    asyncio.run(seed_actor())
    print(f"Fresh deployment migrated to {CURRENT_SCHEMA}; dedicated operator created")


if __name__ == "__main__":
    main()
