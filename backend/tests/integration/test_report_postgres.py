"""Opt-in disposable-schema migration/lease/outbox tests, never shared table edits."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from redis.asyncio import Redis
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.report.artifacts import digest
from app.modules.report.models import ReportOutbox, ReportRecord
from app.modules.report.repository import ReportRepository
from tests.report_support import snapshot

pytestmark = pytest.mark.skipif(
    not os.environ.get("REPORT_TEST_DSN"), reason="REPORT_TEST_DSN not configured"
)


@pytest.fixture
async def sessions():
    schema = "report_test_" + uuid.uuid4().hex
    url = make_url(os.environ["REPORT_TEST_DSN"])
    sync = create_engine(url.set(drivername="postgresql+psycopg2"))
    engine = None
    with sync.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[2] / "alembic")
        )
        scripts = ScriptDirectory.from_config(config)
        with sync.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            with EnvironmentContext(
                config, scripts, fn=lambda rev, _: scripts._upgrade_revs("0017", rev)
            ) as context:
                context.configure(connection=connection)
                context.run_migrations()
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0017"
            )
        engine = create_async_engine(
            url.set(drivername="postgresql+asyncpg"),
            connect_args={"server_settings": {"search_path": schema}},
        )
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if engine:
            await engine.dispose()
        with sync.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        sync.dispose()


async def seed(sessions, *, workspace_id=None, user_id=None):
    value = snapshot()
    row = ReportRecord(
        report_id=uuid.uuid4(),
        workspace_id=workspace_id or uuid.uuid4(),
        requested_by_user_id=user_id or str(uuid.uuid4()),
        report_type="executive_summary",
        output_format="csv",
        status="requested",
        artifact_version=1,
        status_version=1,
        snapshot=value,
        snapshot_sha256=digest(value),
        date_range=value["request"]["date_range"],
        scope=value["request"]["scope"],
        filters=value["request"]["filters"],
        requested_at=datetime.now(UTC),
        artifact_refs=[],
        error_context={},
        correlation_id=uuid.uuid4(),
        queue_status="outbox_pending",
    )
    async with sessions() as db:
        db.add(row)
        ReportRepository(db).enqueue(row)
        await db.commit()
    return row


async def claim(sessions):
    async with sessions() as db:
        return await ReportRepository(db).claim(30)


async def test_dual_claim_restart_expiry_and_stale_terminal_fenced(sessions):
    row = await seed(sessions)
    claimed = await asyncio.gather(claim(sessions), claim(sessions))
    assert sum(item is not None for item in claimed) == 1
    old = next(item for item in claimed if item)
    async with sessions() as db:
        await db.execute(
            update(ReportRecord)
            .where(ReportRecord.report_id == row.report_id)
            .values(lease_expires_at=func.now() - timedelta(seconds=1))
        )
        await db.commit()
    new = await claim(sessions)
    assert new.lease_token != old.lease_token
    async with sessions() as db:
        assert not await ReportRepository(db).finish(old, error={"code": "stale"})
    async with sessions() as db:
        assert await ReportRepository(db).finish(new, error={"code": "current"})
        assert await db.scalar(select(func.count()).select_from(ReportOutbox)) == 2
        assert (await db.get(ReportRecord, row.report_id)).error_context == {
            "code": "current"
        }


async def test_snapshot_and_scope_immutable(sessions):
    row = await seed(sessions)
    for values in (
        {"snapshot": {}},
        {"workspace_id": uuid.uuid4()},
        {"scope": {}},
        {"artifact_version": 0},
    ):
        async with sessions() as db:
            with pytest.raises(DBAPIError):
                await db.execute(
                    update(ReportRecord)
                    .where(ReportRecord.report_id == row.report_id)
                    .values(**values)
                )
            await db.rollback()


async def test_history_exact_total_scoped_even_empty_page(sessions):
    row = await seed(sessions)
    await seed(
        sessions, workspace_id=row.workspace_id, user_id=row.requested_by_user_id
    )
    await seed(sessions, workspace_id=row.workspace_id)
    await seed(sessions, user_id=row.requested_by_user_id)
    async with sessions() as db:
        for page in (1, 2, 3):
            rows, total = await ReportRepository(db).history(
                row.workspace_id, row.requested_by_user_id, page, 1
            )
            assert total == 2 and len(rows) == (1 if page < 3 else 0)


async def test_state_and_outbox_rollback_together(sessions):
    row = await seed(sessions)
    async with sessions() as db:
        current = await db.get(ReportRecord, row.report_id)
        current.status = "failed"
        current.status_version += 1
        ReportRepository(db).enqueue(current)
        await db.flush()
        await db.rollback()
    async with sessions() as db:
        assert (await db.get(ReportRecord, row.report_id)).status == "requested"
        assert await db.scalar(select(func.count()).select_from(ReportOutbox)) == 1


async def test_real_redis_lost_ack_replay_stable_order_receipts(sessions):
    url = os.environ.get("REPORT_TEST_REDIS_URL")
    if not url:
        pytest.skip("Isolated REPORT_TEST_REDIS_URL required")
    row = await seed(sessions)
    current = await claim(sessions)
    async with sessions() as db:
        await ReportRepository(db).finish(current, error={"code": "test_terminal"})
    redis = Redis.from_url(url, decode_responses=True)

    class LostAck:
        async def xadd(self, stream, envelope):
            await redis.xadd(stream, envelope)
            raise ConnectionError("Lost acknowledgement after actual XADD")

    try:
        async with sessions() as db:
            with pytest.raises(ConnectionError):
                await ReportRepository(db).publish_one(LostAck())
        async with sessions() as db:
            assert await ReportRepository(db).publish_one(redis)
            assert await ReportRepository(db).publish_one(redis)
            assert not await ReportRepository(db).publish_one(redis)
            current = await db.get(ReportRecord, row.report_id)
            assert current.queue_status == "queued" and current.stream_entry_id
        events = [
            event
            for _, event in await redis.xrange("stream:report")
            if str(row.report_id) in event["payload"]
        ]
        assert len(events) == 3 and events[0] == events[1]
        assert [item["event_type"] for item in events] == [
            "report.requested",
            "report.requested",
            "report.failed",
        ]
    finally:
        await redis.aclose()
