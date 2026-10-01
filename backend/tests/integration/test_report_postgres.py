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
            # Head, not 0017: the ORM maps ADR-028 columns (claim_attempts, outbox created_at).
            with EnvironmentContext(
                config, scripts, fn=lambda rev, _: scripts._upgrade_revs("head", rev)
            ) as context:
                context.configure(connection=connection)
                context.run_migrations()
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == scripts.get_current_head()
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
    # Lease/outbox fixture has no source rows. Actual telemetry reference transactions
    # are covered with persisted source data in test_retention_complete_postgres.
    value["sections"]["telemetry"].update(rows=[], total=0)
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


async def expire_lease(sessions, report_id):
    async with sessions() as db:
        await db.execute(
            update(ReportRecord)
            .where(ReportRecord.report_id == report_id)
            .values(lease_expires_at=func.now() - timedelta(seconds=1))
        )
        await db.commit()


async def test_claim_attempts_bound_redelivery_then_terminal_attempts_exhausted(sessions):
    row = await seed(sessions)
    for attempt in (1, 2):
        async with sessions() as db:
            claimed = await ReportRepository(db).claim(30, max_attempts=2)
        assert claimed.report_id == row.report_id and claimed.claim_attempts == attempt
        await expire_lease(sessions, row.report_id)  # the attempt crashed
    async with sessions() as db:
        assert await ReportRepository(db).claim(30, max_attempts=2) is None
    async with sessions() as db:
        current = await db.get(ReportRecord, row.report_id)
        assert current.status == "failed" and current.lease_token is None
        assert current.error_context["reason"] == "attempts_exhausted"
        events = (await db.scalars(select(ReportOutbox).order_by(ReportOutbox.status_version))).all()
        assert [event.envelope["event_type"] for event in events] == ["report.requested", "report.failed"]


async def test_lease_renewal_extends_only_a_live_lease(sessions):
    await seed(sessions)
    async with sessions() as db:
        claimed = await ReportRepository(db).claim(30)
    async with sessions() as db:
        assert await ReportRepository(db).renew_lease(claimed, 120)
        renewed = await db.scalar(select(ReportRecord.lease_expires_at).where(
            ReportRecord.report_id == claimed.report_id))
        assert renewed > claimed.lease_expires_at
    await expire_lease(sessions, claimed.report_id)
    async with sessions() as db:
        assert not await ReportRepository(db).renew_lease(claimed, 120)


async def test_history_page_projects_summary_without_snapshot(sessions):
    row = await seed(sessions)
    async with sessions() as db:
        rows, total = await ReportRepository(db).history(row.workspace_id, row.requested_by_user_id, 1, 10)
    assert total == 1 and rows[0].report_id == row.report_id
    assert rows[0].snapshot_summary == {
        "telemetry": {"total": 0, "truncated": False, "omissions": [], "row_count": 0}
    }
    assert not hasattr(rows[0], "snapshot")


async def test_org_storage_usage_and_admission_lock(sessions):
    """ADR-028 C26: usage = recorded artifact sizes + a full reservation per in-flight job."""
    org_workspaces, foreign = [uuid.uuid4(), uuid.uuid4()], uuid.uuid4()
    rows = [(org_workspaces[0], "generated", {"size_bytes": 1000}), (org_workspaces[0], "requested", None),
            (org_workspaces[0], "running", None), (org_workspaces[0], "failed", None),
            (org_workspaces[1], "generated", {"size_bytes": 2500}),
            (org_workspaces[1], "generated", {"size_bytes": "not-a-number"}),
            (foreign, "generated", {"size_bytes": 99999})]
    for workspace_id, status, receipt in rows:
        row = await seed(sessions, workspace_id=workspace_id)
        async with sessions() as db:
            await db.execute(update(ReportRecord).where(ReportRecord.report_id == row.report_id)
                             .values(status=status, receipt=receipt))
            await db.commit()
    async with sessions() as db:
        repo = ReportRepository(db)
        assert await repo.storage_usage(org_workspaces, in_flight_reserve_bytes=700) == 1000 + 700 + 700 + 2500
        assert await repo.storage_usage([foreign], in_flight_reserve_bytes=700) == 99999
        assert await repo.storage_usage([], in_flight_reserve_bytes=700) == 0
    org = uuid.uuid4()
    key = {"key": f"report:org-storage:{org}"}
    probe = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))")
    async with sessions() as holder, sessions() as other:
        await ReportRepository(holder).lock_org_storage(org)
        assert await other.scalar(probe, key) is False  # a concurrent acceptance waits
        await other.rollback()
        await holder.commit()  # released with the accepting transaction
        assert await other.scalar(probe, key) is True
        await other.rollback()


async def test_published_outbox_retention_keeps_pending_and_recent_rows(sessions):
    from app.modules.report.repository import outbox_age_column

    now = datetime.now(UTC)
    rows = {name: await seed(sessions) for name in ("old-published", "recent-published", "old-pending")}
    ages = {"old-published": (now - timedelta(days=40), now - timedelta(days=40)),
            "recent-published": (now - timedelta(days=40), now - timedelta(days=1)),
            "old-pending": (now - timedelta(days=40), None)}
    async with sessions() as db:
        for name, (created, published) in ages.items():
            values = {"published_at": published}
            if outbox_age_column() is not None:
                values["created_at"] = created
            await db.execute(update(ReportOutbox).where(ReportOutbox.report_id == rows[name].report_id).values(**values))
        await db.commit()
    async with sessions() as db:
        assert await ReportRepository(db).purge_published_outbox(retention_days=30, batch_size=10) == 1
    async with sessions() as db:
        remaining = {row.report_id for row in (await db.scalars(select(ReportOutbox))).all()}
    assert remaining == {rows["recent-published"].report_id, rows["old-pending"].report_id}


async def test_new_report_and_first_outbox_row_commit_in_one_unit_of_work_under_the_0030_fk(sessions):
    """ADR-028 0030: the request path adds a report and stages its first event in one flush."""
    async with sessions() as db:
        validated = await db.scalar(text(
            "SELECT convalidated FROM pg_constraint WHERE conname = 'fk_report_outbox_report' "
            "AND connamespace = current_schema()::regnamespace"))
    assert validated is True  # the foreign key is enforced, so a child-first INSERT would fail
    row = await seed(sessions)  # db.add(report); ReportRepository.enqueue(report); commit()
    async with sessions() as db:
        assert await db.scalar(select(ReportOutbox.report_id)) == row.report_id
        assert (await db.get(ReportRecord, row.report_id)).queue_status == "outbox_pending"
