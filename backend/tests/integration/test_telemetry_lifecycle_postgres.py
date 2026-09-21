"""Real PostgreSQL gate in a unique schema; TELEMETRY_TEST_DSN is explicitly opt-in."""

import asyncio
import importlib.util
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.modules.telemetry.cursor import TelemetryCursorService
from app.modules.telemetry.models import TelemetryRecord
from app.modules.telemetry.pin_models import TelemetryEvidencePin
from app.modules.telemetry.archive_models import TelemetryReconciliation
from app.modules.telemetry.pins import (
    REQUIRED_EVIDENCE_OWNERS,
    EvidenceOwnerScope,
    EvidenceReference,
    ProspectiveCoverageContract,
    TelemetryEvidenceService,
)
from app.modules.telemetry.retention import ArchivalAssessmentRequest, TelemetryRetentionService
from app.modules.telemetry.schemas import TelemetryHistoryQuery

pytestmark = pytest.mark.skipif(not os.environ.get("TELEMETRY_TEST_DSN"), reason="TELEMETRY_TEST_DSN not configured")


def migration(connection, direction):
    path = Path(__file__).parents[2] / "alembic/versions/0024_telemetry_evidence_pins.py"
    spec = importlib.util.spec_from_file_location("telemetry_migration_0024", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0023"
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


@pytest.fixture
async def connection():
    engine = create_async_engine(os.environ["TELEMETRY_TEST_DSN"])
    schema = "telemetry_lifecycle_" + uuid.uuid4().hex
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.execute(text(f'SET search_path TO "{schema}"'))
            await conn.run_sync(lambda sync: TelemetryRecord.__table__.create(sync))
            await conn.run_sync(lambda sync: migration(sync, "upgrade"))
            await conn.run_sync(lambda sync: TelemetryReconciliation.__table__.create(sync))
            await conn.commit()
            try:
                yield conn
            finally:
                await conn.rollback()
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                await conn.commit()
    finally:
        await engine.dispose()


def record(workspace, network, observed, number=None, **overrides):
    return TelemetryRecord(**{
        "record_id": uuid.UUID(int=number) if number else uuid.uuid4(),
        "event_id": uuid.uuid4(), "correlation_id": uuid.uuid4(), "device_id": uuid.uuid4(),
        "workspace_id": workspace, "network_id": network, "observed_at": observed,
        "metric": "cpu", "value": 1, "unit": "percent", "source": "fixture", "tags": {}, **overrides,
    })


async def test_keyset_ties_upper_watermark_late_inserts_filters_and_scope(connection):
    workspace, network, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    observed = datetime.now(UTC) - timedelta(days=1)
    async with AsyncSession(connection, expire_on_commit=False) as db:
        db.add_all([record(workspace, network, observed, number) for number in range(1, 7)])
        db.add_all([
            record(uuid.uuid4(), network, observed, 50),
            record(workspace, uuid.uuid4(), observed, 51),
            record(workspace, network, observed, 52, metric="memory"),
            record(workspace, network, observed - timedelta(days=2), 53),
        ])
        await db.commit()
        params = dict(actor_id=actor, workspace_id=workspace, network_id=network, page_size=2,
                      query=TelemetryHistoryQuery(metric="cpu", start_time=observed,
                                                  end_time=observed + timedelta(hours=1)))
        service = TelemetryCursorService(db)
        page = await service.get_history(**params, cursor=None)
        assert [r.record_id.int for r in page.items] == [6, 5]
        upper = page.upper_record_id
        # Later ordinary backfill is below the cursor but excluded by creation cutoff;
        # a higher tuple is excluded even if its creation time predates the cutoff.
        db.add_all([
            record(workspace, network, observed, 100, created_at=observed),
            record(workspace, network, observed + timedelta(minutes=1), 101, created_at=observed),
            record(workspace, network, observed, 0, record_id=uuid.UUID(int=0)),
        ])
        await db.commit()
        seen = list(page.items)
        while page.next_cursor:
            page = await TelemetryCursorService(db).get_history(**params, cursor=page.next_cursor)
            assert page.upper_record_id == upper
            seen.extend(page.items)
        assert [r.record_id.int for r in seen] == [6, 5, 4, 3, 2, 1]
        assert len({r.record_id for r in seen}) == 6
        empty = await service.get_history(**{**params, "query": TelemetryHistoryQuery(metric="absent")}, cursor=None)
        assert empty.items == [] and empty.upper_record_id is None and empty.next_cursor is None


async def test_durable_pins_registration_release_and_historical_fail_closed(connection):
    from app.modules.telemetry.reconciliation import owner_contracts

    owner_contracts()
    workspace, network = uuid.uuid4(), uuid.uuid4()
    scope = EvidenceOwnerScope(owner="report", workspace_id=workspace)
    historical = record(workspace, network, datetime.now(UTC) - timedelta(days=1))
    reference = EvidenceReference(network_id=network, reference_id=uuid.uuid4(), record_id=historical.record_id)
    contract = ProspectiveCoverageContract(version=1, contract="pin-before-reference/v1")
    async with AsyncSession(connection, expire_on_commit=False) as db:
        db.add(historical)
        await db.commit()
        service = TelemetryEvidenceService(db, scope=scope)
        pin = await service.pin(reference)
        await db.commit()
        created = pin.created_at
    async with AsyncSession(connection, expire_on_commit=False) as db:
        service = TelemetryEvidenceService(db, scope=scope)
        assert (await service.pin(reference)).created_at == created
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 1
        for wrong_scope, wrong_reference in [
            (EvidenceOwnerScope(owner="report", workspace_id=uuid.uuid4()), reference),
            (scope, reference.model_copy(update={"network_id": uuid.uuid4()})),
            (scope, reference.model_copy(update={"record_id": uuid.uuid4()})),
        ]:
            with pytest.raises(ValueError, match="unavailable"):
                await TelemetryEvidenceService(db, scope=wrong_scope).pin(wrong_reference)
        for owner in REQUIRED_EVIDENCE_OWNERS:
            # Pin repository contract fixture only; actual owner enumeration is
            # separately exercised at0025 in test_retention_complete_postgres.
            db.add(TelemetryReconciliation(workspace_id=workspace, owner=owner, complete=True, scanned=0, unknown=0))
            await db.flush()
            owner_service = TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner=owner, workspace_id=workspace))
            registration = await owner_service.register_prospective(contract)
            assert (await owner_service.register_prospective(contract)).registered_at == registration.registered_at
        await db.commit()
        prospective = record(workspace, network, datetime.now(UTC))
        db.add(prospective)
        await db.commit()
        request = ArchivalAssessmentRequest(workspace_id=workspace,
            start_time=historical.observed_at - timedelta(seconds=1), end_time=datetime.now(UTC) + timedelta(days=1), batch_size=1)
        result = await TelemetryRetentionService(db).assess(request)
        assert result.pinned == [historical.record_id] and result.next_position
        result2 = await TelemetryRetentionService(db).assess(request.model_copy(update={"after": result.next_position}))
        assert result2.prospective_candidates == [prospective.record_id] and result2.next_position is None
        other = TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="intent", workspace_id=workspace))
        assert await other.release(reference) is False
        wrong_workspace = TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="report", workspace_id=uuid.uuid4()))
        assert await wrong_workspace.release(reference) is False
        assert await service.release(reference.model_copy(update={"network_id": uuid.uuid4()})) is False
        await other.pin(reference)
        assert await service.release(reference) is True
        assert await service.release(reference) is False
        await db.commit()
        still_pinned = await TelemetryRetentionService(db).assess(request)
        assert still_pinned.pinned == [historical.record_id]
        assert await other.release(reference) is True
        await db.commit()
        result = await TelemetryRetentionService(db).assess(request)
        assert result.pinned == [historical.record_id] and result.deleted == 0
        with pytest.raises(ValueError, match="cannot be reused"):
            await service.pin(reference)
        await other.revoke_coverage()
        await db.commit()
        result = await TelemetryRetentionService(db).assess(request.model_copy(update={"batch_size": 100}))
        assert result.coverage_unknown == [prospective.record_id]
        assert result.pinned == [historical.record_id]
        assert result.missing_owners == ["intent"]
        with pytest.raises(ValueError, match="cannot reactivate"):
            await other.register_prospective(contract)


async def test_migration_rollback_preserves_rows_event_uniqueness_and_restricts_pin_delete(connection):
    workspace, network = uuid.uuid4(), uuid.uuid4()
    row = record(workspace, network, datetime.now(UTC))
    record_id, event_id = row.record_id, row.event_id
    async with AsyncSession(connection, expire_on_commit=False) as db:
        db.add(row)
        await db.commit()
        service = TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="alert", workspace_id=workspace))
        ref = EvidenceReference(network_id=network, reference_id=uuid.uuid4(), record_id=row.record_id)
        await service.pin(ref)
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 0
        await service.pin(ref)
        await db.commit()
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(text("DELETE FROM telemetry_records WHERE record_id = :id"), {"id": record_id})
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(record(workspace, network, datetime.now(UTC), event_id=event_id))
                await db.flush()
        await db.commit()
    await connection.run_sync(lambda sync: migration(sync, "downgrade"))
    assert await connection.scalar(text("SELECT count(*) FROM telemetry_records")) == 1
    await connection.run_sync(lambda sync: migration(sync, "upgrade"))
    indexes = (await connection.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"))).scalars().all()
    assert "ix_telemetry_workspace_keyset" in indexes and "ix_telemetry_pins_active" in indexes
    assert await connection.scalar(text("SELECT count(*) FROM telemetry_evidence_pins")) == 0
    await connection.commit()


async def test_concurrent_owner_replay_creates_one_durable_pin(connection):
    workspace, network = uuid.uuid4(), uuid.uuid4()
    row = record(workspace, network, datetime.now(UTC))
    async with AsyncSession(connection) as db:
        db.add(row)
        record_id = row.record_id
        await db.commit()
    schema = await connection.scalar(text("SELECT current_schema()"))
    await connection.commit()
    scope = EvidenceOwnerScope(owner="simulation", workspace_id=workspace)
    reference = EvidenceReference(network_id=network, reference_id=uuid.uuid4(), record_id=record_id)
    engine = create_async_engine(os.environ["TELEMETRY_TEST_DSN"])
    first_inserted, second_started = asyncio.Event(), asyncio.Event()

    async def first():
        async with engine.connect() as conn:
            await conn.execute(text(f'SET search_path TO "{schema}"'))
            await conn.commit()
            async with AsyncSession(conn) as db:
                pin = await TelemetryEvidenceService(db, scope=scope).pin(reference)
                created = pin.created_at
                first_inserted.set()
                await second_started.wait()
                await db.commit()
                return created

    async def second():
        await first_inserted.wait()
        async with engine.connect() as conn:
            await conn.execute(text(f'SET search_path TO "{schema}"'))
            await conn.commit()
            async with AsyncSession(conn) as db:
                second_started.set()
                pin = await TelemetryEvidenceService(db, scope=scope).pin(reference)
                created = pin.created_at
                await db.commit()
                return created

    try:
        created_a, created_b = await asyncio.wait_for(asyncio.gather(first(), second()), timeout=10)
        assert created_a == created_b
        assert await connection.scalar(text("SELECT count(*) FROM telemetry_evidence_pins")) == 1
    finally:
        await engine.dispose()
