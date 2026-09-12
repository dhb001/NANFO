"""Opt-in registry migration/transaction races in a disposable UUID-owned schema."""

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.identity.models import AuditLog
from app.modules.plugin.models import PluginRecord
from app.modules.plugin.schemas import PluginInstallRequest
from app.modules.plugin.service import PluginService

pytestmark = pytest.mark.skipif(not os.environ.get("PLUGIN_TEST_DSN"), reason="PLUGIN_TEST_DSN not configured")


@pytest.fixture
async def sessions(monkeypatch):
    schema = "plugin_test_" + uuid.uuid4().hex
    url = make_url(os.environ["PLUGIN_TEST_DSN"])
    sync = create_engine(url.set(drivername="postgresql+psycopg2"))
    engine = None
    with sync.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        with sync.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            with EnvironmentContext(config, scripts, fn=lambda rev, _: scripts._upgrade_revs("0019", rev)) as context:
                context.configure(connection=connection)
                context.run_migrations()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0019"
            # 0019 is additive/reversible; do not rewrite existing outcome strings.
            connection.execute(text("""INSERT INTO plugins(plugin_key,name,version,signature_status,
                dependency_status,sandbox_status) VALUES('legacy','Legacy','1','verified','compatible','isolated')"""))
            with EnvironmentContext(config, scripts, fn=lambda rev, _: scripts._downgrade_revs("0018", rev)) as context:
                context.configure(connection=connection)
                context.run_migrations()
            with EnvironmentContext(config, scripts, fn=lambda rev, _: scripts._upgrade_revs("0019", rev)) as context:
                context.configure(connection=connection)
                context.run_migrations()
            assert connection.execute(text("SELECT signature_status,dependency_status,sandbox_status FROM plugins"))\
                .one() == ("verified", "compatible", "isolated")
        engine = create_async_engine(url.set(drivername="postgresql+asyncpg"),
                                     connect_args={"server_settings": {"search_path": schema}})
        org = SimpleNamespace(org_id=uuid.UUID(int=1), name="Test", slug="test", created_at=datetime.now(UTC))
        monkeypatch.setattr("app.modules.organization.repository.OrganizationRepository.list_for_user",
                            AsyncMock(return_value=([org], 1)))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if engine:
            await engine.dispose()
        with sync.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        sync.dispose()


def request():
    return PluginInstallRequest(plugin_key="race-plugin", name="Registry Race", version="1.0",
                                signer="nanfo-labs", signature="sig:abcdef1234567890")


async def install(sessions, req=None):
    async with sessions() as db:
        return await PluginService(db=db, redis=None).install_plugin(
            req=req or request(), correlation_id=str(uuid.uuid4()), requested_by_user_id=str(uuid.uuid4()),
        )


async def test_concurrent_install_and_conflicting_manifest(sessions):
    first, second = await asyncio.wait_for(asyncio.gather(install(sessions), install(sessions)), 10)
    assert first.plugin_id == second.plugin_id
    assert sorted([first.idempotent_replay, second.idempotent_replay]) == [False, True]
    changed = request().model_copy(update={"metadata": {"digest": "different"}})
    with pytest.raises(HTTPException) as exc:
        await install(sessions, changed)
    assert exc.value.status_code == 409


async def test_concurrent_uninstall_single_audit_and_stable_reinstall(sessions):
    original = await install(sessions)

    async def uninstall():
        async with sessions() as db:
            await PluginService(db=db, redis=None).uninstall_plugin(
                plugin_id=original.plugin_id, correlation_id=str(uuid.uuid4()), requested_by_user_id=str(uuid.uuid4()),
            )

    await asyncio.wait_for(asyncio.gather(uninstall(), uninstall()), 10)
    async with sessions() as db:
        row = await db.get(PluginRecord, original.plugin_id)
        assert row.status == "uninstalled" and row.uninstalled_at is not None and row.enabled is False
        audit = (await db.scalars(select(AuditLog))).all()
        assert len(audit) == 1 and audit[0].event_type == "plugin.registry.removed"
        assert audit[0].metadata_["previous_status"] == "installed"
    restored = await install(sessions)
    assert restored.plugin_id == original.plugin_id and restored.installed_at == original.installed_at
    assert restored.status == "installed" and restored.uninstalled_at is None and restored.enabled is False
    async with sessions() as db:
        assert len((await db.scalars(select(AuditLog))).all()) == 1


async def test_uninstall_wins_after_inflight_enable_and_audit_failure_rolls_back(sessions, monkeypatch):
    original = await install(sessions)
    entered, release = asyncio.Event(), asyncio.Event()

    async def publish(**kwargs):
        entered.set()
        await release.wait()
        return "queued", "100-0", None

    monkeypatch.setattr(PluginService, "_publish_lifecycle_event", staticmethod(publish))

    async def enable():
        async with sessions() as db:
            await PluginService(db=db, redis=None).enable_plugin(
                plugin_id=original.plugin_id, correlation_id=str(uuid.uuid4()), requested_by_user_id=str(uuid.uuid4()),
            )

    async def uninstall():
        async with sessions() as db:
            await PluginService(db=db, redis=None).uninstall_plugin(
                plugin_id=original.plugin_id, correlation_id=str(uuid.uuid4()), requested_by_user_id=str(uuid.uuid4()),
            )

    enabled = asyncio.create_task(enable())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        removed = asyncio.create_task(uninstall())
        release.set()
        await asyncio.wait_for(asyncio.gather(enabled, removed), 10)
    finally:
        release.set()
        await enabled
    async with sessions() as db:
        row = await db.get(PluginRecord, original.plugin_id)
        assert row.status == "uninstalled" and row.enabled is False
    await install(sessions)
    monkeypatch.setattr("app.modules.plugin.service.append_audit_log", AsyncMock(side_effect=RuntimeError("audit down")))
    with pytest.raises(RuntimeError):
        await uninstall()
    async with sessions() as db:
        row = await db.get(PluginRecord, original.plugin_id)
        assert row.status == "installed" and row.uninstalled_at is None
