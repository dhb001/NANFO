"""Opt-in private PostgreSQL fleet races; every test owns an isolated schema."""

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from app.modules.telemetry.fleet_models import FleetBatch, FleetDevice
from app.modules.telemetry.fleet_repository import FleetLock, FleetRepository
from app.modules.telemetry.service import TelemetryIngestionService
from app.modules.telemetry.snmp_config import SNMPError
from tests.unit.test_fleet import config as fleet_config_fixture
from tests.unit.test_fleet import worker

config = fleet_config_fixture

pytestmark = pytest.mark.skipif(not os.environ.get("FLEET_TEST_DSN"), reason="FLEET_TEST_DSN not configured")


@pytest.fixture
async def database():
    schema = "fleet_test_" + uuid.uuid4().hex
    url = make_url(os.environ["FLEET_TEST_DSN"])
    sync = create_engine(url.set(drivername="postgresql+psycopg2"))
    engine = lock_engine = None
    with sync.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        with sync.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            for target, direction in [("0026", "upgrade"), ("0025", "downgrade"), ("0026", "upgrade")]:
                revisions = getattr(scripts, f"_{direction}_revs")
                with EnvironmentContext(config, scripts, fn=lambda rev, _, revisions=revisions, target=target: revisions(target, rev)) as context:
                    context.configure(connection=connection)
                    context.run_migrations()
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == target
        options = {"server_settings": {"search_path": schema, "application_name": schema}}
        engine = create_async_engine(url.set(drivername="postgresql+asyncpg"), connect_args=options)
        lock_engine = create_async_engine(url.set(drivername="postgresql+asyncpg"), connect_args=options, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        repository = FleetRepository(sessions, lease_seconds=3, timeout_seconds=1)
        yield SimpleNamespace(sessions=sessions, repository=repository, locks=FleetLock(lock_engine, repository),
                              schema=schema, engine=engine, lock_engine=lock_engine)
    finally:
        if engine:
            await engine.dispose()
        if lock_engine:
            await lock_engine.dispose()
        with sync.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        sync.dispose()


async def expire(database, device_id):
    async with database.sessions() as db:
        await db.execute(update(FleetDevice).where(FleetDevice.device_id == device_id).values(
            lease_until=func.clock_timestamp() - timedelta(seconds=1),
            next_poll_at=func.clock_timestamp() - timedelta(seconds=1),
        ))
        await db.commit()


async def test_lease_race_expiry_and_stale_token_fencing(database):
    repo = database.repository
    device = uuid.uuid4()
    claims = await asyncio.gather(*(repo.claim(device, uuid.uuid4()) for _ in range(12)))
    assert sum(claim is not None for claim in claims) == 1
    first = next(claim for claim in claims if claim)
    await expire(database, device)
    second = await repo.claim(device, uuid.uuid4())
    assert second.token != first.token
    with pytest.raises(SNMPError, match="lease_lost"):
        await repo.check(first, renew=True)
    await repo.check(second, renew=True)


async def test_expired_lease_cannot_duplicate_live_io_and_no_transaction(database):
    device = uuid.uuid4()
    async with database.locks.acquire(device, uuid.uuid4()) as first:
        assert first is not None
        await expire(database, device)
        async with database.locks.acquire(device, uuid.uuid4()) as second:
            assert second is None
        async with database.sessions() as db:
            active = (await db.execute(text(
                "SELECT state, xact_start FROM pg_stat_activity WHERE application_name=:name AND pid != pg_backend_pid()"
            ), {"name": database.schema})).all()
            assert active and all(state == "idle" and transaction is None for state, transaction in active)
    async with database.locks.acquire(device, uuid.uuid4()) as replacement:
        assert replacement is not None and replacement[0].token != first[0].token


async def test_lost_ack_restart_replays_exact_events_through_existing_bus(database, config, fake_redis, monkeypatch):
    instance, _, _, _, transport, _ = worker(config, repository=database.repository, locks=database.locks,
                                           ingestion=TelemetryIngestionService(fake_redis))
    target = instance.manifest.targets[0]
    original = database.repository.acknowledge
    monkeypatch.setattr(database.repository, "acknowledge", AsyncMock(side_effect=ConnectionError("lost ack")))
    assert await instance.collect_target(target) == "collection_deferred"
    first = await fake_redis.xrange("stream:telemetry")
    assert len(first) == 1 and transport.get.await_count == 1
    await expire(database, target.device_id)
    monkeypatch.setattr(database.repository, "acknowledge", original)
    restarted, _, _, _, new_transport, _ = worker(config, repository=database.repository, locks=database.locks,
                                                 ingestion=TelemetryIngestionService(fake_redis))
    assert await restarted.collect_target(target) == "published"
    new_transport.get.assert_not_awaited()
    entries = await fake_redis.xrange("stream:telemetry")
    # Envelope timestamp can differ; durable identity/payload/correlation cannot.
    for field in ("event_id", "correlation_id", "payload"):
        assert entries[0][1][field] == entries[1][1][field]
    async with database.sessions() as db:
        batch = await db.scalar(select(FleetBatch))
        assert batch.status == "published" and batch.cursor == 3


async def test_expired_batch_records_outcome_and_backoff_is_per_device(database):
    repo = database.repository
    lease = await repo.claim(uuid.uuid4(), uuid.uuid4())
    batch = await repo.stage(lease, digest="a" * 64, samples=[{"event_id": str(uuid.uuid4())}],
                             expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert (await repo.ready(lease, batch.batch_id, batch.binding_sha256)).status == "expired"
    await repo.finish(lease, outcome="expired", interval=1, backoff_max=8, failed=False)
    health = (await repo.health([lease.device_id]))[0]
    assert health["expired_samples"] == 1 and health["last_published_at"] is None
    assert await repo.claim(lease.device_id, uuid.uuid4()) is None
    assert await repo.claim(uuid.uuid4(), uuid.uuid4()) is not None
    await expire(database, lease.device_id)
    lease = await repo.claim(lease.device_id, uuid.uuid4())
    await repo.finish(lease, outcome="collection_deferred", interval=1, backoff_max=8, failed=True)
    health = (await repo.health([lease.device_id]))[0]
    assert health["failures"] == 1
    assert 1.5 < (datetime.fromisoformat(health["next_poll_at"]) - datetime.now(UTC)).total_seconds() <= 2


async def test_real_competing_workers_never_read_same_device_concurrently(database, config):
    first, _, _, _, transport, _ = worker(config, repository=database.repository, locks=database.locks)
    second, _, _, _, other_transport, _ = worker(config, repository=database.repository, locks=database.locks)
    entered, release = asyncio.Event(), asyncio.Event()
    counters = transport.get.return_value

    async def get(*_):
        entered.set()
        await release.wait()
        return counters

    transport.get.side_effect = get
    target = first.manifest.targets[0]
    running = asyncio.create_task(first.collect_target(target))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert await second.collect_target(target) == "not_due_or_owned"
        other_transport.get.assert_not_awaited()
    finally:
        release.set()
        await running


async def test_sigkill_writer_releases_session_lock_and_restart_replays_committed_spool(database):
    """A real process dies after durable stage and before any external publication."""
    device_id, event_id = uuid.uuid4(), uuid.uuid4()
    program = '''
import asyncio, os, uuid
from datetime import UTC, datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.modules.telemetry.fleet_repository import FleetRepository, FleetLock
async def main():
    engine = create_async_engine(os.environ['FLEET_TEST_DSN'], poolclass=NullPool,
        connect_args={'server_settings': {'search_path': os.environ['FLEET_SCHEMA']}})
    repo = FleetRepository(async_sessionmaker(engine, expire_on_commit=False), lease_seconds=3, timeout_seconds=1)
    async with FleetLock(engine, repo).acquire(uuid.UUID(os.environ['FLEET_DEVICE']), uuid.uuid4()) as acquired:
        lease, _ = acquired
        await repo.stage(lease, digest='a'*64, samples=[{'event_id': os.environ['FLEET_EVENT']}],
            expires_at=datetime.now(UTC)+timedelta(seconds=30))
        print('durable', flush=True)
        await asyncio.Event().wait()
asyncio.run(main())
'''
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-c", program, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, "FLEET_SCHEMA": database.schema, "FLEET_DEVICE": str(device_id), "FLEET_EVENT": str(event_id)},
    )
    try:
        assert await asyncio.wait_for(child.stdout.readline(), 10) == b"durable\n"
        async with database.locks.acquire(device_id, uuid.uuid4()) as competing:
            assert competing is None
        child.kill()
        await child.wait()
        assert child.returncode == -9
        await expire(database, device_id)
        async with database.locks.acquire(device_id, uuid.uuid4()) as acquired:
            assert acquired is not None
            lease, check = acquired
            await check()
            batch = await database.repository.pending(lease)
            assert batch.samples == [{"event_id": str(event_id)}] and batch.cursor == 0
            await database.repository.acknowledge(lease, batch.batch_id, 0)
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()
