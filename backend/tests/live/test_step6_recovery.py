"""Opt-in tests against already-running services, never global stream consumers.

From backend/: NANFO_STEP6_LIVE=1 poetry run pytest tests/live/test_step6_recovery.py -q --no-cov
Uses backend/.env credentials without printing them. Creates only UUID-namespaced
Redis keys/groups and a disposable PostgreSQL database (requires CREATEDB).
All owned keys/database are removed in finally blocks. No API server is started.
"""

import asyncio
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg2
import pytest
import redis.asyncio as aioredis
from alembic.config import Config
from dotenv import dotenv_values
from psycopg2 import sql
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.core.config import Settings
from app.events.bus import completion_key, process_entry, run_consumer_loop
from app.events.consumers.audit_consumer import handle_audit_event
from app.events.realtime import ApiRealtimeLease
from app.modules.identity.models import AuditLog
from app.modules.identity.repository import AuditLogRepository


@pytest.fixture
def live_settings():
    import os

    if os.environ.get("NANFO_STEP6_LIVE") != "1":
        pytest.skip("requires explicit NANFO_STEP6_LIVE=1")
    # Explicit kwargs override unit-test environment, not application security.
    return Settings(**dotenv_values(Path(__file__).resolve().parents[2] / ".env"))


async def test_real_redis_bounded_reclaim_poison_and_api_exclusion(live_settings):
    redis = aioredis.from_url(live_settings.REDIS_URL, decode_responses=True,
                             socket_timeout=5, socket_connect_timeout=5)
    prefix = f"test:step6:{uuid.uuid4().hex}"
    stream, group, dlq, lease_key = (f"{prefix}:{suffix}" for suffix in ("stream", "group", "dlq", "lease"))
    event = {"event_id": str(uuid.uuid4()), "event_type": "intent.validated", "payload": "{}"}
    calls = []
    delivered = asyncio.Event()

    async def handler(event):
        calls.append(event["event_id"])
        if len(calls) == 3:
            delivered.set()

    events = [{**event, "event_id": str(uuid.uuid4())} for _ in range(3)]
    keys = [stream, dlq, lease_key]
    keys.extend(completion_key(stream, group, e["event_id"], handler) for e in events)
    task = None
    try:
        await redis.ping()
        await redis.xgroup_create(stream, group, "0", mkstream=True)
        for item in events:
            await redis.xadd(stream, item)
        # A dead process owns three pending entries; recover at most one per page.
        await redis.xreadgroup(group, "dead-api", {stream: ">"}, count=3)
        assert (await redis.xpending(stream, group))["pending"] == 3
        await asyncio.sleep(0.03)
        claimed = await redis.xautoclaim(stream, group, "probe", 20, count=1)
        assert len(claimed[1]) == 1
        assert (await redis.xpending(stream, group))["pending"] == 3
        await asyncio.sleep(0.03)
        task = asyncio.create_task(run_consumer_loop(
            redis, stream, group, "replacement-api", {event["event_type"]: handler},
            dead_letter_key=dlq, reclaim_idle_ms=20, batch_size=1,
        ))
        await asyncio.wait_for(delivered.wait(), 10)
        async with asyncio.timeout(3):
            while (await redis.xpending(stream, group))["pending"]:
                await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert len(set(calls)) == 3
        # ADR-028: the stable instance name is used verbatim (no per-start suffix).
        assert "replacement-api" in {c["name"] for c in await redis.xinfo_consumers(stream, group)}

        poison_id = await redis.xadd(stream, {**event, "payload": "["})
        messages = await redis.xreadgroup(group, "poison-probe", {stream: ">"}, count=1)
        fields = messages[0][1][0][1]
        await redis.set(dlq, "force-dlq-failure")
        with pytest.raises(aioredis.ResponseError):
            await process_entry(redis, stream, group, poison_id, fields, {}, dead_letter_key=dlq)
        assert (await redis.xpending(stream, group))["pending"] == 1
        await redis.delete(dlq)
        await process_entry(redis, stream, group, poison_id, fields, {}, dead_letter_key=dlq)
        assert (await redis.xpending(stream, group))["pending"] == 0
        assert (await redis.xrange(dlq))[0][1]["failed_entry_id"] == poison_id

        # Exercise actual redis-py response decoding, not just the dispatcher.
        binary_id = await redis.xadd(stream, {**event, "payload": b"\xff"})
        task = asyncio.create_task(run_consumer_loop(
            redis, stream, group, "binary-poison", {}, dead_letter_key=dlq,
            reclaim_idle_ms=20, batch_size=1,
        ))
        async with asyncio.timeout(5):
            while await redis.xlen(dlq) != 2 or (await redis.xpending(stream, group))["pending"]:
                await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        from redis.client import NEVER_DECODE

        raw_dlq = await redis.execute_command("XRANGE", dlq, "-", "+", **{NEVER_DECODE: True})
        assert raw_dlq[-1][1][b"failed_entry_id"] == binary_id.encode()
        assert raw_dlq[-1][1][b"payload"] == b"\xff"

        lost = asyncio.Event()
        async with ApiRealtimeLease(redis, key=lease_key, ttl_seconds=0.3, on_lost=lost.set) as first:
            with pytest.raises(RuntimeError, match="exactly one"):
                async with ApiRealtimeLease(redis, key=lease_key, on_lost=lost.set):
                    pytest.fail("second API accepted")
            await asyncio.sleep(0.4)
            assert first.healthy and not lost.is_set()
            await redis.set(lease_key, "successor", px=2000)
            await asyncio.wait_for(lost.wait(), 1)
        assert await redis.get(lease_key) == "successor"
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await redis.delete(*keys)
        await redis.aclose()


async def test_disposable_postgres_migration0012_audit_transaction_and_replay(live_settings):
    name = f"nanfo_step6_{uuid.uuid4().hex}"
    settings = live_settings.model_copy(update={"POSTGRES_DB": name})
    admin = psycopg2.connect(
        host=live_settings.POSTGRES_HOST, port=live_settings.POSTGRES_PORT,
        user=live_settings.POSTGRES_USER, password=live_settings.POSTGRES_PASSWORD,
        dbname=live_settings.POSTGRES_DB, connect_timeout=5,
    )
    admin.autocommit = True
    engine = None
    created = False
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))

    def migrate(revision, *, downgrade=False):
        with patch("app.core.config.get_settings", return_value=settings):
            (command.downgrade if downgrade else command.upgrade)(config, revision)

    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        created = True
        await asyncio.to_thread(migrate, "0011")
        engine = create_async_engine(settings.POSTGRES_DSN, connect_args={"timeout": 5})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        historical_id = uuid.uuid4()
        async with engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO audit_logs (log_id, event_type, correlation_id) VALUES (:id, 'auth.user.logged_in', :id)"
            ), {"id": historical_id})
        await asyncio.to_thread(migrate, "0012")
        event_id = uuid.uuid4()
        values = {"event_id": event_id, "event_type": "intent.execution_started",
                  "actor_id": None, "correlation_id": uuid.uuid4(), "metadata": {"test": "step6"}}
        async with sessions() as db:
            await AuditLogRepository(db).append(**values)
            await db.rollback()
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.event_id == event_id)) == 0

        async def append():
            async with sessions() as db:
                entry = await AuditLogRepository(db).append(**values)
                await db.commit()
                return entry

        inserted = await asyncio.wait_for(asyncio.gather(append(), append()), 10)
        assert sum(entry is not None for entry in inserted) == 1
        assert await append() is None  # Restart/replay without Redis completion state.
        with patch("app.events.consumers.audit_consumer.AsyncSessionLocal", sessions):
            for _ in range(2):
                await handle_audit_event({
                    "event_id": str(event_id), "event_type": values["event_type"],
                    "correlation_id": str(values["correlation_id"]), "payload": values["metadata"],
                })
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(AuditLog)) == 2
            historical = await db.get(AuditLog, historical_id)
            assert historical.event_id is None
            assert await db.scalar(text("SELECT version_num FROM alembic_version")) == "0012"
        await engine.dispose()
        await asyncio.to_thread(migrate, "0011", downgrade=True)
        await asyncio.to_thread(migrate, "0012")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM audit_logs")) == 2
    finally:
        if engine:
            await engine.dispose()
        if created:
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()
