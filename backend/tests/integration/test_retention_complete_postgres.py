"""ADR023 actual owner transactions and races, only disposable opt-in PostgreSQL."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.alert.detector import MeasuredObservation
from app.modules.alert.measured import MeasuredAlertService
from app.modules.autonomy.models import AutonomyControl, AutonomyDecision
from app.modules.intent.models import Intent
from app.modules.report.models import ReportRecord
from app.modules.simulation.models import Simulation
from app.modules.telemetry.archive import TelemetryArchiveStore
from app.modules.telemetry.archive_models import TelemetryArchiveReceipt
from app.modules.telemetry.models import TelemetryRecord
from app.modules.telemetry.pin_models import TelemetryEvidencePin
from app.modules.telemetry.pins import EvidenceOwnerScope, EvidenceReference, ProspectiveCoverageContract, TelemetryEvidenceService
from app.modules.telemetry.reconciliation import TelemetryReconciliationService, owner_contracts
from app.modules.telemetry.retention import ArchivalAssessmentRequest, TelemetryRetentionService
from app.modules.telemetry.service import TelemetryPersistenceService

pytestmark = pytest.mark.skipif(not os.environ.get("RETENTION_TEST_DSN"), reason="disposable RETENTION_TEST_DSN required")


@pytest.fixture
async def sessions():
    owner_contracts()
    schema = "retention_" + uuid.uuid4().hex
    url = make_url(os.environ["RETENTION_TEST_DSN"])
    sync = create_engine(url.set(drivername="postgresql+psycopg2"))
    with sync.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = None
    try:
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        with sync.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            with EnvironmentContext(config, scripts, fn=lambda rev, _: scripts._upgrade_revs("0025", rev)) as context:
                context.configure(connection=conn)
                context.run_migrations()
        engine = create_async_engine(url.set(drivername="postgresql+asyncpg"),
                                    connect_args={"server_settings": {"search_path": schema}})
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if engine:
            await engine.dispose()
        with sync.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        sync.dispose()


def metric(workspace, network, **changes):
    now = datetime.now(UTC)
    return TelemetryRecord(**dict(record_id=uuid.uuid4(), event_id=uuid.uuid4(), correlation_id=uuid.uuid4(),
        device_id=uuid.uuid4(), workspace_id=workspace, network_id=network, metric="latency_ms", value=120.0,
        unit="ms", observed_at=now, created_at=now, source="emulation", tags={}, **changes))


def report(row, report_id=None):
    return ReportRecord(report_id=report_id or uuid.uuid4(), workspace_id=row.workspace_id,
        network_id=row.network_id, report_type="telemetry", output_format="csv", artifact_version=1,
        requested_by_user_id="fixture", requested_at=datetime.now(UTC), correlation_id=uuid.uuid4(),
        snapshot={"sections": {"telemetry": {"rows": [{"record_id": str(row.record_id),
            "network_id": str(row.network_id), "value": row.value}]}}})


async def reconcile(sessions, workspace):
    for owner in owner_contracts():
        for _ in range(30):
            async with sessions() as db:
                result = await TelemetryReconciliationService(db).step(workspace_id=workspace, owner=owner, limit=1)
                await db.commit()
            if result["complete"]:
                break
        else:
            raise AssertionError("unbounded reconciliation")


def request(workspace):
    now = datetime.now(UTC)
    return ArchivalAssessmentRequest(workspace_id=workspace, start_time=now - timedelta(days=1),
                                     end_time=now + timedelta(hours=1), batch_size=100)


@pytest.fixture
def store(tmp_path):
    os.chmod(tmp_path, 0o700)
    return TelemetryArchiveStore(tmp_path)


async def test_real_delete_restore_tamper_global_old_event_and_tenant(sessions, store):
    workspace, network = uuid.uuid4(), uuid.uuid4()
    await reconcile(sessions, workspace)
    row = metric(workspace, network)
    foreign = metric(uuid.uuid4(), network)
    async with sessions() as db:
        db.add_all([row, foreign])
        await db.commit()
    async with sessions() as db:
        result = await TelemetryRetentionService(db).assess(request(workspace))
        assert result.prospective_candidates == [row.record_id]
        assert await db.get(TelemetryRecord, row.record_id)
        result = await TelemetryRetentionService(db).apply(request(workspace), store=store)
        assert result.deleted == 1
        await db.commit()
    async with sessions() as db:
        assert await db.get(TelemetryRecord, row.record_id) is None
        assert await db.get(TelemetryRecord, foreign.record_id)
        # Global replay, even with malformed/foreign payload, must not recreate it.
        assert not await TelemetryPersistenceService(db).persist_event({"event_id": str(row.event_id), "payload": {}})
        with pytest.raises(ValueError, match="workspace"):
            await TelemetryRetentionService(db).restore(workspace_id=foreign.workspace_id,
                                                       record_id=row.record_id, store=store)
        receipt = await db.get(TelemetryArchiveReceipt, row.record_id)
        path = store.root / receipt.sha256
        data = path.read_bytes()
        path.write_bytes(b"x" * len(data))
        with pytest.raises(ValueError, match="checksum"):
            await TelemetryRetentionService(db).restore(workspace_id=workspace, record_id=row.record_id, store=store)
        assert await db.get(TelemetryRecord, row.record_id) is None
        path.write_bytes(data)
        assert await TelemetryRetentionService(db).restore(workspace_id=workspace, record_id=row.record_id, store=store)
        await db.commit()
        restored = await db.get(TelemetryRecord, row.record_id)
        assert restored.event_id == row.event_id and restored.value == row.value
        assert not await TelemetryPersistenceService(db).persist_event({"event_id": str(row.event_id)})


async def test_report_crash_replay_transaction_and_released_audit(sessions, store):
    workspace, network = uuid.uuid4(), uuid.uuid4()
    await reconcile(sessions, workspace)
    row = metric(workspace, network)
    identity = uuid.uuid4()
    async with sessions() as db:
        db.add(row)
        await db.commit()
        db.add(report(row, identity))
        await db.flush()
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 1
        db.expunge(row)
        await db.rollback()  # process died before report acceptance
    async with sessions() as db:
        assert await db.get(ReportRecord, identity) is None
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 0
        db.add(report(row, identity))
        await db.commit()
    async with sessions() as db:
        current = await db.get(ReportRecord, identity)
        current.status = "failed"  # worker replay still uses frozen reference identity
        await db.commit()
        pins = list((await db.scalars(select(TelemetryEvidencePin))).all())
        assert len(pins) == 1
        pin = pins[0]
        svc = TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="report", workspace_id=workspace))
        await svc.release(EvidenceReference(network_id=network, reference_id=pin.reference_id, record_id=row.record_id))
        await db.commit()
        result = await TelemetryRetentionService(db).apply(request(workspace), store=store)
        assert result.deleted == 0 and result.pinned == [row.record_id]


async def test_all_five_owners_pin_actual_writes_and_enumerate_history(sessions):
    workspace, network = uuid.uuid4(), uuid.uuid4()
    rows = [metric(workspace, network) for _ in range(5)]
    now = datetime.now(UTC)
    async with sessions() as db:
        db.add_all(rows)
        await db.commit()
        db.add(report(rows[0]))
        db.add(Intent(intent_id=uuid.uuid4(), workspace_id=workspace, network_id=network, intent_kind="fixture",
            intent_payload={"evidence": [f"telemetry_record:{rows[1].record_id}"]}, correlation_id=uuid.uuid4(),
            requested_by_user_id="fixture", requested_at=now))
        db.add(Simulation(simulation_id=uuid.uuid4(), workspace_id=workspace, network_id=network,
            scenario_id=uuid.uuid4(), scenario_name="fixture", state="completed", status="completed", risk_gate="blocked",
            audit_provenance={"source_record_ids": [str(rows[2].record_id)]}, requested_by_user_id="fixture", requested_at=now))
        db.add(AutonomyControl(network_id=network, workspace_id=workspace))
        await db.flush()
        db.add(AutonomyDecision(decision_id=uuid.uuid4(), network_id=network, workspace_id=workspace, actor_id="fixture",
            mode="monitor", control_revision=0, status="blocked", observation={"samples": [{"record_id": str(rows[3].record_id)}]}))
        await db.commit()
        row = rows[4]
        observation = MeasuredObservation(event_id=row.event_id, correlation_id=row.correlation_id,
            device_id=row.device_id, network_id=network, workspace_id=workspace, metric="latency_ms", value=120.0,
            unit="ms", source="emulation", observed_at=row.observed_at, tags=dict(synthetic=False,
                execution_mode="emulation", quality="measured", freshness="fresh", run_id=str(uuid.uuid4()),
                topology_id="campus-small-v1", measurement_method="ping_rtt", peer_host="h2", latency_semantics="RTT"))
        service = MeasuredAlertService(db=db)
        org_id = uuid.uuid4()
        service.authorize_observation = AsyncMock(return_value=org_id)
        await service.apply_observation(observation, org_id)
        pins = list((await db.scalars(select(TelemetryEvidencePin))).all())
        assert {pin.owner for pin in pins} == set(owner_contracts())
        assert {pin.record_id for pin in pins} == {row.record_id for row in rows}
    await reconcile(sessions, workspace)
    for owner, contract in owner_contracts().items():
        after, found = None, set()
        for _ in range(10):
            async with sessions() as db:
                page = await contract(db, workspace_id=workspace, after=after, limit=1)
                found.update(ref.record_id for item in page.items for ref in item.references)
            after = page.next_cursor
            if after is None:
                break
        assert found, owner


async def test_pin_delete_exclusion_both_orders(sessions, store):
    workspace, network = uuid.uuid4(), uuid.uuid4()
    await reconcile(sessions, workspace)
    first, second = metric(workspace, network), metric(workspace, network)
    async with sessions() as db:
        db.add_all([first, second])
        await db.commit()
    async with sessions() as pin_db, sessions() as delete_db:
        pin_db.add(report(first))
        await pin_db.flush()
        result = await TelemetryRetentionService(delete_db).apply(request(workspace), store=store)
        assert result.deleted == 1  # locked first skipped; unreferenced second deleted
        await delete_db.commit()
        await pin_db.commit()
    third = metric(workspace, network)
    async with sessions() as db:
        db.add(third)
        await db.commit()
    async with sessions() as delete_db:
        result = await TelemetryRetentionService(delete_db).apply(request(workspace), store=store)
        assert result.deleted == 1
        started = asyncio.Event()

        async def pin_deleted():
            async with sessions() as db:
                db.add(report(third))
                started.set()
                with pytest.raises(ValueError, match="unavailable"):
                    await db.commit()
                await db.rollback()

        task = asyncio.create_task(pin_deleted())
        await started.wait()
        await asyncio.sleep(.05)
        assert not task.done()
        await delete_db.commit()
        await asyncio.wait_for(task, 3)


async def test_coverage_requires_real_enumeration_legacy_retained(sessions, store):
    workspace, network = uuid.uuid4(), uuid.uuid4()
    old = metric(workspace, network)
    async with sessions() as db:
        db.add(old)
        await db.commit()
        svc = TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="report", workspace_id=workspace))
        with pytest.raises(ValueError, match="reconciliation"):
            await svc.register_prospective(ProspectiveCoverageContract(version=1, contract="pin-before-reference/v1"))
        # Historical pre-integration content is inserted directly as a fixture.
        await db.execute(text("INSERT INTO reports (report_id, workspace_id, report_type, output_format, status, "
            "correlation_id, requested_by_user_id, requested_at, queue_status, date_range, scope, filters, artifact_refs, error_context) "
            "VALUES (:id, :ws, 'telemetry', 'csv', 'failed', :corr, 'fixture', now(), 'failed', '{}', '{}', '{}', '[]', '{}')"),
            {"id": uuid.uuid4(), "ws": workspace, "corr": uuid.uuid4()})
        await db.commit()
    await reconcile(sessions, workspace)
    async with sessions() as db:
        result = await TelemetryReconciliationService(db).step(workspace_id=workspace, owner="report")
        assert result["unknown"] == 1
        result = await TelemetryRetentionService(db).apply(request(workspace), store=store)
        assert result.deleted == 0 and result.coverage_unknown == [old.record_id]


async def test_report_service_source_capture_crash_and_idempotent_replay(sessions, store, monkeypatch):
    from app.modules.report.service import ReportService

    workspace, network = uuid.uuid4(), uuid.uuid4()
    await reconcile(sessions, workspace)
    row = metric(workspace, network)
    monkeypatch.setattr("app.modules.report.service.get_settings", lambda: SimpleNamespace(
        REPORTS_STORAGE_PATH=str(store.root), REPORTS_MAX_BYTES=1048576, REPORTS_MIN_FREE_BYTES=0))
    args = dict(workspace_id=workspace, network_id=network, report_type="telemetry", output_format="csv",
        date_range={"start": (row.observed_at - timedelta(seconds=1)).isoformat(),
                    "end": (row.observed_at + timedelta(seconds=1)).isoformat()}, scope={}, filters={},
        fail_generation=False, idempotency_key="crash-replay", correlation_id=str(uuid.uuid4()),
        requested_by_user_id="scoped-fixture")
    async with sessions() as db:
        db.add(row)
        await db.commit()
    async with sessions() as db:
        svc = ReportService(db=db, redis=None)
        # Authority is a separate owner-service dependency, data capture is real.
        svc.authorize_generation = AsyncMock()

        async def crash():
            await db.flush()
            raise RuntimeError("process dies before commit")

        db.commit = crash
        with pytest.raises(RuntimeError):
            await svc.generate_report(**args)
        await db.rollback()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ReportRecord)) == 0
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 0
        svc = ReportService(db=db, redis=None)
        svc.authorize_generation = AsyncMock()
        result = await svc.generate_report(**args)
        replay = await svc.generate_report(**args)
        assert replay["idempotent_replay"] and replay["report_id"] == result["report_id"]
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 1
        assessment = await TelemetryRetentionService(db).apply(request(workspace), store=store)
        assert assessment.deleted == 0 and assessment.pinned == [row.record_id]


async def test_worker_bounded_apply_and_concurrent_ingestion(sessions, store):
    from app.modules.telemetry.retention_worker import TelemetryRetentionWorker

    workspace, network = uuid.uuid4(), uuid.uuid4()
    await reconcile(sessions, workspace)
    row = metric(workspace, network)
    event = {"event_id": str(row.event_id), "correlation_id": str(row.correlation_id), "payload": {
        "workspace_id": str(workspace), "network_id": str(network), "device_id": str(row.device_id),
        "metric": row.metric, "value": row.value, "unit": row.unit, "source": row.source,
        "observed_at": row.observed_at.isoformat(), "tags": {}}}

    async def ingest():
        async with sessions() as db:
            created = await TelemetryPersistenceService(db).persist_event(event)
            await db.commit()
            return created

    assert sorted(await asyncio.gather(ingest(), ingest())) == [False, True]
    async with sessions() as db:
        db.add_all([metric(workspace, network) for _ in range(3)])
        await db.commit()
    worker = TelemetryRetentionWorker(sessions, settings={"max_batches": 2, "interval_seconds": 0})
    bounded = request(workspace).model_copy(update={"batch_size": 1})
    dry = await worker.sweep(bounded)
    assert len(dry) == 2 and all(page["deleted"] == 0 for page in dry)
    applied = await worker.sweep(bounded, apply=True, archive_root=store.root)
    assert len(applied) == 2 and sum(page["deleted"] for page in applied) == 2
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(TelemetryRecord)) == 2


async def test_foreign_owner_reference_cannot_commit(sessions):
    row = metric(uuid.uuid4(), uuid.uuid4())
    async with sessions() as db:
        db.add(row)
        await db.commit()
        foreign = report(row)
        foreign.workspace_id = uuid.uuid4()
        db.add(foreign)
        with pytest.raises(ValueError, match="owner scope"):
            await db.commit()
        await db.rollback()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ReportRecord)) == 0


async def test_new_autonomy_runtime_owner_enumeration(sessions):
    """Service contract sees actual0027 frames/journals without runtime file edits."""
    from app.modules.autonomy.execution_models import AutonomousObservation, AutonomousProviderState
    from app.modules.autonomy.service import telemetry_reference_page

    workspace, network = uuid.uuid4(), uuid.uuid4()
    row = metric(workspace, network)
    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(lambda conn: AutonomousObservation.__table__.create(conn, checkfirst=True))
        await connection.run_sync(lambda conn: AutonomousProviderState.__table__.create(conn, checkfirst=True))
        db.add(row)
        await db.commit()
        db.add(AutonomousObservation(observation_sha256="a" * 64, network_id=network, workspace_id=workspace,
            observation={"samples": [{"record_id": str(row.record_id)}]}, safety_observation={}))
        db.add(AutonomousProviderState(network_id=network, workspace_id=workspace, installation_sha256="b" * 64,
            state={}, evidence=[f"telemetry_record:{row.record_id}"]))
        await db.commit()
        after, seen = None, set()
        for _ in range(10):
            page = await telemetry_reference_page(db, workspace_id=workspace, after=after, limit=1)
            seen.update(ref.record_id for item in page.items for ref in item.references)
            after = page.next_cursor
            if after is None:
                break
        assert seen == {row.record_id}
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 2


async def test_archive_failure_rolls_back_deletion_and_tombstone(sessions, store):
    from app.modules.telemetry.archive_models import TelemetryEventTombstone

    workspace, network = uuid.uuid4(), uuid.uuid4()
    await reconcile(sessions, workspace)
    row = metric(workspace, network)
    async with sessions() as db:
        db.add(row)
        await db.commit()

    def interrupted(data):
        store.write(data)  # durable orphan is safe; DB deletion has not happened
        raise OSError("archive acknowledgement lost")

    async with sessions() as db:
        with pytest.raises(OSError):
            await TelemetryRetentionService(db).apply(request(workspace), store=SimpleNamespace(write=interrupted))
        await db.rollback()
    async with sessions() as db:
        assert await db.get(TelemetryRecord, row.record_id)
        assert await db.get(TelemetryEventTombstone, row.event_id) is None
        result = await TelemetryRetentionService(db).apply(request(workspace), store=store)
        assert result.deleted == 1
        await db.commit()


async def test_cli_dry_apply_restore_against_disposable_schema(sessions, store, monkeypatch):
    from scripts import telemetry_retention as cli

    workspace, network = uuid.uuid4(), uuid.uuid4()
    await reconcile(sessions, workspace)
    row = metric(workspace, network)
    async with sessions() as db:
        db.add(row)
        await db.commit()
    monkeypatch.setenv("TELEMETRY_RETENTION_DSN", os.environ["RETENTION_TEST_DSN"])
    monkeypatch.setattr(cli, "create_async_engine", lambda dsn: sessions.kw["bind"])
    bounds = request(workspace)
    args = ["--workspace-id", str(workspace), "--start-time", bounds.start_time.isoformat(),
            "--end-time", bounds.end_time.isoformat(), "--archive-root", str(store.root)]
    dry = await cli.run(cli.parser().parse_args(["dry-run", *args]))
    assert dry[0]["deleted"] == 0 and dry[0]["prospective_candidates"] == [str(row.record_id)]
    applied = await cli.run(cli.parser().parse_args(["apply", *args]))
    assert applied[0]["deleted"] == 1
    restored = await cli.run(cli.parser().parse_args(["restore", *args, "--record-id", str(row.record_id)]))
    assert restored["restored"] is True


@pytest.mark.parametrize("target", ["ancestor", "root"])
@pytest.mark.parametrize("replacement", ["symlink", "directory"])
@pytest.mark.parametrize("timing", ["before", "publication", "readback"])
async def test_archive_path_replacement_never_deletes_source(
    sessions, tmp_path, monkeypatch, target, replacement, timing,
):
    from app.modules.telemetry.archive_models import TelemetryEventTombstone
    from app.modules.telemetry.archive_repository import TelemetryArchiveRepository

    parent = tmp_path / "parent"
    root = parent / "archive"
    parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    store = TelemetryArchiveStore(root)
    workspace, network = uuid.uuid4(), uuid.uuid4()
    await reconcile(sessions, workspace)
    row = metric(workspace, network)
    async with sessions() as db:
        db.add(row)
        await db.commit()

    def replace():
        path = parent if target == "ancestor" else root
        path.rename(tmp_path / "original")
        alternate = tmp_path / "alternate"
        alternate.mkdir(mode=0o700)
        if replacement == "symlink":
            path.symlink_to(alternate, target_is_directory=True)
        else:
            path.mkdir(mode=0o700)
        if target == "ancestor":
            (path / "archive").mkdir(mode=0o700)

    with monkeypatch.context() as patch:
        deletion = AsyncMock()
        patch.setattr(TelemetryArchiveRepository, "archive_and_delete", deletion)
        if timing == "before":
            replace()
        elif timing == "publication":
            original = os.link

            def link(*args, **kwargs):
                replace()
                return original(*args, **kwargs)

            patch.setattr(os, "link", link)
        else:
            original = store._read

            def read(*args):
                data = original(*args)
                replace()
                return data

            patch.setattr(store, "_read", read)
        async with sessions() as db:
            with pytest.raises((OSError, ValueError)):
                await TelemetryRetentionService(db).apply(request(workspace), store=store)
            deletion.assert_not_awaited()
            # Even a caller committing after refusal cannot lose the source row.
            await db.commit()
        async with sessions() as db:
            assert await db.get(TelemetryRecord, row.record_id)
            assert await db.get(TelemetryEventTombstone, row.event_id) is None
            assert await db.get(TelemetryArchiveReceipt, row.record_id) is None

    # Restore the original mount/path and restart the store; durable orphan bytes
    # from a refused write are safely replayable and restore works after restart.
    path = parent if target == "ancestor" else root
    if replacement == "symlink":
        path.unlink()
    else:
        if target == "ancestor":
            (path / "archive").rmdir()
        path.rmdir()
    (tmp_path / "original").rename(path)
    async with sessions() as db:
        result = await TelemetryRetentionService(db).apply(request(workspace), store=TelemetryArchiveStore(root))
        assert result.deleted == 1
        await db.commit()
    async with sessions() as db:
        assert await TelemetryRetentionService(db).restore(workspace_id=workspace, record_id=row.record_id,
                                                           store=TelemetryArchiveStore(root))
        await db.commit()
        assert (await db.get(TelemetryRecord, row.record_id)).event_id == row.event_id
