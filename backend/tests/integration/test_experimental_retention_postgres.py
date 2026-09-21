"""Actual0029 coverage invalidation, pin-before-write and retention race tests."""

import asyncio
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.modules.autonomy.experimental.models import LabAction, LabReceipt
from app.modules.autonomy.experimental.persistence import LabRepository
from app.modules.autonomy.experimental.schemas import contract_digest, utcnow
from app.modules.autonomy.service import telemetry_reference_page
from app.modules.telemetry.archive_models import TelemetryReconciliation
from app.modules.telemetry.models import TelemetryRecord
from app.modules.telemetry.pin_models import TelemetryEvidencePin, TelemetryReferenceCoverage
from app.modules.telemetry.pins import EvidenceOwnerScope, ProspectiveCoverageContract, TelemetryEvidenceService
from app.modules.telemetry.reconciliation import TelemetryReconciliationService
from app.modules.telemetry.retention import TelemetryRetentionService
from app.modules.telemetry.service import TelemetryPersistenceService
from tests.experimental_lab_support import case
from tests.integration import test_retention_complete_postgres as support
from tests.integration.test_retention_complete_postgres import metric, reconcile, request

pytestmark = support.pytestmark
base_sessions = support.sessions
store = support.store


def migrate(connection, revision, direction="upgrade"):
    names = {"0027": "autonomous_execution", "0028": "experimental_lab", "0029": "experimental_telemetry_coverage"}
    path = Path(__file__).parents[2] / f"alembic/versions/{revision}_{names[revision]}.py"
    spec = importlib.util.spec_from_file_location("experimental_retention_migration_" + revision, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


@pytest.fixture
async def sessions(base_sessions):
    async with base_sessions.begin() as db:
        conn = await db.connection()
        for revision in ("0027", "0028", "0029"):
            await conn.run_sync(lambda sync, rev=revision: migrate(sync, rev))
    return base_sessions


async def setup_run(sessions):
    c = case()
    c.policy = c.policy.model_copy(update={"runtime": c.policy.runtime.model_copy(
        update={"resource_id": "retention-" + uuid4().hex})})
    async with sessions.begin() as db:
        await LabRepository(db).create(c.policy, uuid4())
    return c


def receipt(c, payload, identity=None):
    return LabReceipt(receipt_id=identity or uuid4(), run_id=c.policy.run_id, kind="fixture-evidence",
        payload=payload, payload_sha256=contract_digest(payload), created_at=utcnow())


async def all_references(db, workspace, after=None):
    items = []
    for _ in range(100):
        page = await telemetry_reference_page(db, workspace_id=workspace, after=after, limit=1)
        items.extend(page.items)
        after = page.next_cursor
        if after is None:
            return items
    raise AssertionError("reference pagination failed to terminate")


async def test_nested_fields_receipts_pin_atomically_and_enumerate_scope(sessions, store):
    c = await setup_run(sessions)
    foreign = await setup_run(sessions)
    records = [metric(c.policy.workspace_id, c.policy.network_id) for _ in range(8)]
    other = metric(foreign.policy.workspace_id, foreign.policy.network_id)
    async with sessions.begin() as db:
        db.add_all([*records, other])
    fields = {
        "frame": {"observation": {"samples": [{"record_id": str(records[0].record_id)}],
            "evidence": [f"telemetry_record:{records[1].record_id}"]},
            "snapshot": {"history": {"source_record_ids": [str(records[2].record_id)]}}},
        "inference": {"proposal": {"evidence": [f"telemetry_record:{records[3].record_id}"]}},
        "simulation": {"result": {"telemetry_record_id": str(records[4].record_id)}},
        "command": {"observation_json": json.dumps({"record_id": str(records[5].record_id)})},
        "prepared": {"baseline": {"record_ids": [str(records[6].record_id)]}},
    }
    async with sessions.begin() as db:
        db.add(LabAction(request_id=uuid4(), run_id=c.policy.run_id, phase="restored", **fields))
        db.add(receipt(c, {"verification": {"telemetry_record_ids": [str(records[7].record_id)]}}))
        db.add(receipt(foreign, {"record_id": str(other.record_id)}))
    async with sessions() as db:
        pins = (await db.scalars(select(TelemetryEvidencePin).where(
            TelemetryEvidencePin.workspace_id == c.policy.workspace_id))).all()
        assert {p.record_id for p in pins} == {r.record_id for r in records}
        assert all(p.owner == "autonomy" and p.network_id == c.policy.network_id for p in pins)
        items = await all_references(db, c.policy.workspace_id)
        assert {ref.record_id for item in items for ref in item.references} == {r.record_id for r in records}
        # A legacy completed-stage cursor cannot skip oldest history in v2.
        assert await all_references(db, c.policy.workspace_id, '[5,null]') == items
        assert (await TelemetryRetentionService(db).apply(request(c.policy.workspace_id), store=store)).deleted == 0


async def test_receipt_rollback_replay_and_nonreference_uuid(sessions):
    c = await setup_run(sessions)
    row = metric(c.policy.workspace_id, c.policy.network_id)
    identity = uuid4()
    async with sessions.begin() as db:
        db.add(row)
    payload = {"evidence": [f"telemetry_record:{row.record_id}"], "snapshot_id": str(uuid4())}
    async with sessions() as db:
        db.add(receipt(c, payload, identity))
        await db.flush()
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 1
        async with sessions() as observer:
            assert await observer.get(LabReceipt, identity) is None
            assert await observer.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 0
        await db.rollback()
    async with sessions.begin() as db:
        db.add(receipt(c, payload, identity))
        db.add(receipt(c, {"snapshot_id": str(uuid4()), "run_id": str(uuid4()), "sha256": "a" * 64}))
    async with sessions.begin() as db:
        row = await db.get(LabReceipt, identity)
        row.payload = dict(payload)  # ORM replay of identical immutable evidence.
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 1


@pytest.mark.parametrize("mismatch", ["workspace", "network", "malformed", "missing"])
async def test_nested_wrong_scope_or_invalid_reference_rolls_back_owner(sessions, mismatch):
    c = await setup_run(sessions)
    row = metric(uuid4() if mismatch == "workspace" else c.policy.workspace_id,
                 uuid4() if mismatch == "network" else c.policy.network_id)
    async with sessions.begin() as db:
        db.add(row)
    identity = uuid4()
    locator = "bad" if mismatch == "malformed" else str(uuid4()) if mismatch == "missing" else str(row.record_id)
    async with sessions() as db:
        db.add(receipt(c, {"workspace_id": str(row.workspace_id), "network_id": str(row.network_id),
                           "deep": {"record_id": locator}}, identity))
        with pytest.raises(ValueError):
            await db.commit()
        await db.rollback()
    async with sessions() as db:
        assert await db.get(LabReceipt, identity) is None
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 0


async def test0029_invalidates_only_autonomy_then_rescans_legacy_history(sessions):
    c = await setup_run(sessions)
    workspace = c.policy.workspace_id
    await reconcile(sessions, workspace)
    row = metric(workspace, c.policy.network_id)
    identity = uuid4()
    async with sessions.begin() as db:
        db.add(row)
        await db.flush()
        # Simulate a pre0029 durable receipt: Core SQL intentionally bypasses the
        # newly installed ORM guard, just as historical bytes predate that guard.
        payload = {"verification": {"source_record_id": str(row.record_id)}}
        await db.execute(LabReceipt.__table__.insert().values(receipt_id=identity, run_id=c.policy.run_id,
            kind="pre0029", payload=payload, payload_sha256=contract_digest(payload), created_at=utcnow()))
        before = (await db.get(TelemetryReferenceCoverage, (workspace, "report"))).registered_at
        conn = await db.connection()
        await conn.run_sync(lambda sync: migrate(sync, "0029"))
    async with sessions() as db:
        progress = await db.get(TelemetryReconciliation, (workspace, "autonomy"))
        assert not progress.complete and progress.cursor is None and progress.scanned == 0
        assert (await db.get(TelemetryReferenceCoverage, (workspace, "autonomy"))).revoked_at
        assert (await db.get(TelemetryReferenceCoverage, (workspace, "report"))).registered_at == before
        assert "autonomy" in (await TelemetryRetentionService(db).assess(request(workspace))).missing_owners
        with pytest.raises(ValueError, match="reconciliation"):
            await TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="autonomy", workspace_id=workspace)
                ).register_prospective(ProspectiveCoverageContract(version=1, contract="pin-before-reference/v1"))
    await reconcile(sessions, workspace)
    async with sessions() as db:
        progress = await db.get(TelemetryReconciliation, (workspace, "autonomy"))
        assert progress.complete and progress.scanned >= 3
        assert (await db.get(TelemetryReferenceCoverage, (workspace, "autonomy"))).revoked_at is None
        assert await db.scalar(select(TelemetryEvidencePin.record_id).where(TelemetryEvidencePin.record_id == row.record_id))
        assert row.record_id in (await TelemetryRetentionService(db).assess(request(workspace))).pinned
        conn = await db.connection()
        await conn.run_sync(lambda sync: migrate(sync, "0029", "downgrade"))
        await db.commit()
        assert (await db.get(TelemetryReferenceCoverage, (workspace, "autonomy"))).revoked_at


async def test_receipt_pin_wins_against_retention_delete(sessions, store):
    c = await setup_run(sessions)
    await reconcile(sessions, c.policy.workspace_id)
    row = metric(c.policy.workspace_id, c.policy.network_id)
    async with sessions.begin() as db:
        db.add(row)
    async with sessions() as writer:
        writer.add(receipt(c, {"deep": {"record_id": str(row.record_id)}}))
        await writer.flush()  # reference pins hold FOR SHARE until owner commits.
        async with sessions.begin() as deletion:
            result = await TelemetryRetentionService(deletion).apply(request(c.policy.workspace_id), store=store)
            assert result.deleted == 0
        await writer.commit()
    async with sessions.begin() as db:
        result = await TelemetryRetentionService(db).apply(request(c.policy.workspace_id), store=store)
        assert result.pinned == [row.record_id] and result.deleted == 0


async def test_delete_wins_late_receipt_fails_and_event_replay_stays_deleted(sessions, store):
    c = await setup_run(sessions)
    await reconcile(sessions, c.policy.workspace_id)
    row = metric(c.policy.workspace_id, c.policy.network_id)
    async with sessions.begin() as db:
        db.add(row)
    entered = asyncio.Event()
    async def late_reference():
        async with sessions.begin() as db:
            db.add(receipt(c, {"record_id": str(row.record_id)}))
            entered.set()
            with pytest.raises(ValueError, match="unavailable"):
                await db.flush()
            await db.rollback()
    async with sessions.begin() as deletion:
        assert (await TelemetryRetentionService(deletion).apply(request(c.policy.workspace_id), store=store)).deleted == 1
        task = asyncio.create_task(late_reference())
        await entered.wait()
        await asyncio.sleep(.03)
        assert not task.done()
    await asyncio.wait_for(task, 5)
    async with sessions.begin() as db:
        assert await db.get(TelemetryRecord, row.record_id) is None
        assert not await TelemetryPersistenceService(db).persist_event({"event_id": str(row.event_id), "payload": {}})
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 0


async def test_run_policy_references_and_empty_evidence_do_not_guess_ids(sessions):
    c = case()
    row = metric(c.policy.workspace_id, c.policy.network_id)
    c.policy = c.policy.model_copy(update={"assumptions": {
        "record_id": str(row.record_id), "snapshot_id": str(uuid4())}})
    async with sessions.begin() as db:
        db.add(row)
    async with sessions.begin() as db:
        await LabRepository(db).create(c.policy, uuid4())
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 1
        items = await all_references(db, c.policy.workspace_id)
        assert {r.record_id for i in items for r in i.references} == {row.record_id}


async def test_migration_resets_all_autonomy_cursors_without_other_owner_metadata(sessions):
    workspaces = [uuid4(), uuid4()]
    for workspace in workspaces:
        await reconcile(sessions, workspace)
    async with sessions.begin() as db:
        first = await db.get(TelemetryReconciliation, (workspaces[0], "autonomy"))
        first.complete, first.cursor = False, '[4,"' + str(uuid4()) + '"]'
        second = await db.get(TelemetryReconciliation, (workspaces[1], "autonomy"))
        assert second.complete
        conn = await db.connection()
        await conn.run_sync(lambda sync: migrate(sync, "0029"))
    async with sessions() as db:
        for workspace in workspaces:
            progress = await db.get(TelemetryReconciliation, (workspace, "autonomy"))
            assert not progress.complete and progress.cursor is None and progress.unknown == progress.scanned == 0
            assert (await db.get(TelemetryReferenceCoverage, (workspace, "autonomy"))).revoked_at
            assert (await db.get(TelemetryReferenceCoverage, (workspace, "report"))).revoked_at is None
            assert (await db.get(TelemetryReconciliation, (workspace, "report"))).complete


async def test_historical_invalid_reference_is_unknown_not_silent_coverage(sessions):
    c = await setup_run(sessions)
    async with sessions.begin() as db:
        payload = {"record_id": "malformed"}
        await db.execute(LabReceipt.__table__.insert().values(receipt_id=uuid4(), run_id=c.policy.run_id,
            kind="pre0029", payload=payload, payload_sha256=contract_digest(payload), created_at=utcnow()))
    result = None
    for _ in range(30):
        async with sessions.begin() as db:
            result = await TelemetryReconciliationService(db).step(
                workspace_id=c.policy.workspace_id, owner="autonomy", limit=1)
        if result["complete"]:
            break
    assert result["complete"] and result["unknown"] >= 1
    assert result["historical_coverage"] == "unknown_retained"
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 0


async def test_direct_receipt_import_wires_guard_and_released_reference_cannot_replay(sessions):
    from app.modules.telemetry.pins import EvidenceReference
    c = await setup_run(sessions)
    row = metric(c.policy.workspace_id, c.policy.network_id)
    item = receipt(c, {"record_id": str(row.record_id)})
    async with sessions.begin() as db:
        db.add(row)
    async with sessions.begin() as db:
        db.add(item)
    async with sessions.begin() as db:
        pin = await db.scalar(select(TelemetryEvidencePin))
        await TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="autonomy", workspace_id=c.policy.workspace_id)
            ).release(EvidenceReference(network_id=pin.network_id, reference_id=pin.reference_id, record_id=pin.record_id))
    async with sessions() as db:
        # Same reference identity replay must fail, not acknowledge a released pin.
        from app.modules.autonomy.experimental.references import experimental_telemetry_references
        stored = await db.get(LabReceipt, item.receipt_id)
        refs = await db.run_sync(lambda _: experimental_telemetry_references(stored).references)
        with pytest.raises(ValueError, match="Released"):
            await TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="autonomy", workspace_id=c.policy.workspace_id)
                ).pin(refs[0])
