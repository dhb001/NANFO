"""Opt-in real migrations, authorization, optimistic races and atomic audit rollback.

SPATIAL_TEST_DSN must identify an authorized disposable PostgreSQL database.
Only a UUID-named schema is created/dropped; no Docker or deployment operations.
"""

import asyncio
import hashlib
import json
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.identity.models import AuditLog
from app.modules.identity.service import append_audit_log
from app.modules.network.models import Device, Network
from app.modules.network.spatial_models import SpatialSceneRecord, SpatialSceneRevision
from app.modules.network.spatial_repository import SpatialSceneRepository
from app.modules.network.spatial_schemas import ReplaceSpatialSceneRequest
from app.modules.network.spatial_service import SpatialSceneService
from app.modules.network.spatial_transforms import world_geometry
from app.modules.simulation.spatial_rf import spatial_document_hash
from app.modules.organization.models import Organization, OrgMember, Workspace
from tests.spatial_support import ACTOR_ID, DEVICE_ID, NETWORK_ID, WORKSPACE_ID, replace_payload, spatial_object
from tests.unit.test_spatial_geometry import dimensioned_objects

pytestmark = pytest.mark.skipif(not os.environ.get("SPATIAL_TEST_DSN"), reason="SPATIAL_TEST_DSN not configured")
ORG_ID = uuid.UUID(int=305)


@pytest.fixture
async def sessions():
    schema = "spatial_test_" + uuid.uuid4().hex
    url = make_url(os.environ["SPATIAL_TEST_DSN"])
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
            for target, direction in (("0022", "up"), ("0020", "down"), ("0022", "up")):
                migrate = scripts._upgrade_revs if direction == "up" else scripts._downgrade_revs
                with EnvironmentContext(config, scripts, fn=lambda rev, _, t=target, m=migrate: m(t, rev)) as context:
                    context.configure(connection=connection)
                    context.run_migrations()
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == target
        engine = create_async_engine(url.set(drivername="postgresql+asyncpg"),
                                     connect_args={"server_settings": {"search_path": schema}})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            db.add(Organization(org_id=ORG_ID, name="Spatial Test", slug="spatial-test"))
            await db.flush()
            db.add(Workspace(workspace_id=WORKSPACE_ID, org_id=ORG_ID, name="Spatial Test"))
            db.add(OrgMember(org_id=ORG_ID, user_id=ACTOR_ID, org_role="Operator"))
            db.add(Network(network_id=NETWORK_ID, workspace_id=WORKSPACE_ID, name="Spatial Test"))
            await db.flush()
            db.add(Device(device_id=DEVICE_ID, network_id=NETWORK_ID, hostname="spatial-ap", device_type="ap"))
            await db.commit()
        yield factory
    finally:
        if engine:
            await engine.dispose()
        with sync.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        sync.dispose()


async def replace(sessions, revision=0, objects=None):
    async with sessions() as db:
        return await SpatialSceneService(db, None).replace_scene(
            network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), correlation_id="postgres-spatial-test",
            req=ReplaceSpatialSceneRequest.model_validate(replace_payload(revision, objects)),
        )


async def read(sessions):
    async with sessions() as db:
        return await SpatialSceneService(db, None).get_scene(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID))


async def test_dimensioned_save_history_restore_preserves_legacy_body_and_hash(sessions):
    legacy = await replace(sessions, objects=[spatial_object("legacy", "building"), spatial_object("null", geometry=None)])
    legacy_body = legacy.model_dump(mode="json", exclude={"revision"})
    legacy_hash = spatial_document_hash(legacy)
    expected_audit_hash = hashlib.sha256(json.dumps(
        legacy_body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
    ).encode()).hexdigest()
    dimensioned = await replace(sessions, 1, dimensioned_objects())
    loaded = await read(sessions)
    assert loaded == dimensioned
    assert world_geometry(loaded) == world_geometry(dimensioned)
    assert loaded.objects[-1].geometry.material.attenuation_db == 7.5
    async with sessions() as db:
        service = SpatialSceneService(db, None)
        first = await service.get_revision(network_id=NETWORK_ID, revision=1, actor_user_id=str(ACTOR_ID))
        second = await service.get_revision(network_id=NETWORK_ID, revision=2, actor_user_id=str(ACTOR_ID))
        assert spatial_document_hash(first) == legacy_hash
        assert first.model_dump(mode="json", exclude={"revision"}) == legacy_body
        assert second == dimensioned
        stored = await db.get(SpatialSceneRevision, (NETWORK_ID, 1))
        assert "geometry" not in stored.scene["objects"][0]
        assert stored.scene["objects"][1]["geometry"] is None
        audit = (await db.scalars(select(AuditLog).order_by(AuditLog.timestamp))).first()
        assert audit.metadata_["scene_sha256"] == expected_audit_hash
    restored = await replace(sessions, 2, legacy_body["objects"])
    assert restored.revision == 3
    assert restored.model_dump(mode="json", exclude={"revision"}) == legacy_body
    async with sessions() as db:
        assert (await db.get(SpatialSceneRevision, (NETWORK_ID, 2))).scene == dimensioned.model_dump(mode="json", exclude={"revision"})


async def test_initial_read_persist_reload_replace_and_audit(sessions):
    assert (await read(sessions)).revision == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SpatialSceneRecord)) == 0
    objects = [spatial_object("floor", "floor"), spatial_object(parent_id="floor", device_id=str(DEVICE_ID))]
    first = await replace(sessions, objects=objects)
    assert first.revision == 1 and (await read(sessions)) == first
    second = await replace(sessions, 1)
    assert second.revision == 2 and second.objects == [] and (await read(sessions)) == second
    async with sessions() as db:
        rows = (await db.scalars(select(AuditLog).order_by(AuditLog.timestamp))).all()
        assert len(rows) == 2
        assert [row.metadata_["previous_revision"] for row in rows] == [0, 1]
        assert [row.metadata_["revision"] for row in rows] == [1, 2]
        assert rows[0].actor_id == ACTOR_ID and rows[0].resource_id == NETWORK_ID
        assert rows[0].metadata_["scene_sha256"] != rows[1].metadata_["scene_sha256"]


@pytest.mark.parametrize("initial_revision", [0, 1])
async def test_simultaneous_first_and_existing_writers_have_one_winner(sessions, initial_revision):
    if initial_revision:
        await replace(sessions)
    start = asyncio.Event()

    async def writer(name):
        await start.wait()
        try:
            return await replace(sessions, initial_revision, [spatial_object(name)])
        except HTTPException as exc:
            return exc

    tasks = [asyncio.create_task(writer(name)) for name in ("first", "second")]
    start.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    winners = [result for result in results if not isinstance(result, HTTPException)]
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(winners) == len(failures) == 1
    assert failures[0].status_code == 409 and failures[0].detail["code"] == "SPATIAL_REVISION_CONFLICT"
    assert await read(sessions) == winners[0]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == initial_revision + 1
        assert await db.scalar(select(func.count()).select_from(SpatialSceneRevision)) == initial_revision + 1
        stored = await db.get(SpatialSceneRevision, (NETWORK_ID, winners[0].revision))
        assert stored.scene == winners[0].model_dump(mode="json", exclude={"revision"})


@pytest.mark.parametrize("existing", [False, True])
async def test_failure_after_actual_audit_insert_rolls_back_both_rows(sessions, monkeypatch, existing):
    before = await replace(sessions) if existing else await read(sessions)

    async def fail_after_append(**kwargs):
        await append_audit_log(**kwargs)
        raise RuntimeError("injected failure after audit insert")

    monkeypatch.setattr("app.modules.network.spatial_service.append_audit_log", fail_after_append)
    with pytest.raises(RuntimeError, match="injected"):
        await replace(sessions, before.revision, [spatial_object("failed")])
    assert await read(sessions) == before
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == int(existing)
        assert await db.scalar(select(func.count()).select_from(SpatialSceneRecord)) == int(existing)
        assert await db.scalar(select(func.count()).select_from(SpatialSceneRevision)) == int(existing)


async def test_foreign_missing_deleted_devices_leave_scene_and_audit_unchanged(sessions):
    other_network = uuid.UUID(int=401)
    foreign_device = uuid.UUID(int=402)
    async with sessions() as db:
        db.add(Network(network_id=other_network, workspace_id=WORKSPACE_ID, name="Other"))
        await db.flush()
        db.add(Device(device_id=foreign_device, network_id=other_network, hostname="other", device_type="ap"))
        await db.execute(update(Device).where(Device.device_id == DEVICE_ID).values(deleted_at=func.now()))
        await db.commit()
    for device_id in (DEVICE_ID, foreign_device, uuid.UUID(int=403)):
        with pytest.raises(HTTPException) as error:
            await replace(sessions, objects=[spatial_object(device_id=str(device_id))])
        assert error.value.status_code == 422
        assert error.value.detail["code"] == "SPATIAL_DEVICE_SCOPE_INVALID"
    assert (await read(sessions)).revision == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


async def test_real_membership_downgrade_and_network_soft_delete(sessions):
    await replace(sessions)
    async with sessions() as db:
        await db.execute(update(OrgMember).where(OrgMember.org_id == ORG_ID).values(org_role="Read-Only"))
        await db.commit()
    assert (await read(sessions)).revision == 1
    with pytest.raises(HTTPException) as error:
        await replace(sessions, 1)
    assert error.value.status_code == 403
    async with sessions() as db:
        await db.execute(update(Network).where(Network.network_id == NETWORK_ID).values(deleted_at=func.now()))
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await read(sessions)
    assert error.value.status_code == 404


async def test_uncommitted_replacement_is_invisible_to_readers(sessions, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_audit(**kwargs):
        await append_audit_log(**kwargs)
        entered.set()
        await release.wait()

    monkeypatch.setattr("app.modules.network.spatial_service.append_audit_log", delayed_audit)
    task = asyncio.create_task(replace(sessions, objects=[spatial_object("pending")]))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert (await read(sessions)).revision == 0
        async with sessions() as db:
            page = await SpatialSceneService(db, None).list_history(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID))
            assert page.total == 0 and page.items == []
    finally:
        release.set()
        await asyncio.wait_for(task, 5)
    assert (await read(sessions)).revision == 1


async def test_commit_failure_rolls_back_pending_scene_and_audit(sessions, monkeypatch):
    async with sessions() as db:
        monkeypatch.setattr(db, "commit", AsyncMock(side_effect=RuntimeError("commit unavailable")))
        with pytest.raises(RuntimeError, match="commit unavailable"):
            await SpatialSceneService(db, None).replace_scene(
                network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), correlation_id="commit-failure",
                req=ReplaceSpatialSceneRequest.model_validate(replace_payload()),
            )
    assert (await read(sessions)).revision == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
        assert await db.scalar(select(func.count()).select_from(SpatialSceneRevision)) == 0


async def test_stale_first_revision_leaves_no_placeholder_or_audit(sessions):
    with pytest.raises(HTTPException) as error:
        await replace(sessions, 3)
    assert error.value.detail["code"] == "SPATIAL_REVISION_CONFLICT"
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SpatialSceneRecord)) == 0
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
    assert (await replace(sessions)).revision == 1


@pytest.mark.parametrize("barrier", ["network", "device", "scene"])
@pytest.mark.parametrize("revocation", ["downgrade", "remove"])
async def test_membership_revoked_while_waiting_on_owner_lock_denies_write(sessions, barrier, revocation):
    """Use actual PostgreSQL blocking, including a strongly retained stale identity."""
    existing = barrier == "scene"
    if existing:
        await replace(sessions)
    async with sessions() as blocker, sessions() as writer:
        member = await writer.get(OrgMember, (ORG_ID, ACTOR_ID))
        assert member.org_role == "Operator"
        # Keep `member` alive: re-query alone would otherwise mask the identity-map bug.
        writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
        lock_query = {
            "network": select(Network.network_id).where(Network.network_id == NETWORK_ID),
            "device": select(Device.device_id).where(Device.device_id == DEVICE_ID),
            "scene": select(SpatialSceneRecord.network_id).where(SpatialSceneRecord.network_id == NETWORK_ID),
        }[barrier]
        await blocker.scalar(lock_query.with_for_update())
        task = asyncio.create_task(SpatialSceneService(writer, None).replace_scene(
            network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), correlation_id="revocation-lock-barrier",
            req=ReplaceSpatialSceneRequest.model_validate(replace_payload(
                int(existing), [spatial_object(device_id=str(DEVICE_ID))],
            )),
        ))

        async def wait_for_database_lock():
            async with sessions() as observer:
                while not await observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                                                {"pid": writer_pid}):
                    if task.done():
                        await task
                        pytest.fail("Writer finished before reaching the lock barrier")
                    await asyncio.sleep(0.01)

        try:
            await asyncio.wait_for(wait_for_database_lock(), 5)
            async with sessions() as revoker:
                change = {"org_role": "Read-Only"} if revocation == "downgrade" else {"deleted_at": func.now()}
                await revoker.execute(update(OrgMember).where(
                    OrgMember.org_id == ORG_ID, OrgMember.user_id == ACTOR_ID,
                ).values(**change))
                await revoker.commit()
            assert member.org_role == "Operator"  # The writer still holds the stale ORM value.
            await blocker.rollback()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(task, 5)
            assert error.value.status_code == 403
        finally:
            await blocker.rollback()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == int(existing)
        assert await db.scalar(select(func.count()).select_from(SpatialSceneRecord)) == int(existing)
        assert await db.scalar(select(func.count()).select_from(SpatialSceneRevision)) == int(existing)
        if existing:
            row = await db.get(SpatialSceneRecord, NETWORK_ID)
            assert row.revision == 1 and row.scene["objects"] == []


async def test_history_pagination_bodies_and_restore_as_new_revision(sessions):
    async with sessions() as db:
        svc = SpatialSceneService(db, None)
        assert (await svc.list_history(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID))).total == 0
        with pytest.raises(HTTPException) as error:
            await svc.get_revision(network_id=NETWORK_ID, revision=0, actor_user_id=str(ACTOR_ID))
        assert error.value.detail["code"] == "SPATIAL_REVISION_NOT_FOUND"
    first = await replace(sessions, objects=[spatial_object("original")])
    await replace(sessions, 1, [spatial_object("new")])
    await replace(sessions, 2, [spatial_object("new")])  # Equal content still appends.
    async with sessions() as db:
        svc = SpatialSceneService(db, None)
        page = await svc.list_history(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), page_size=2)
        assert page.total == 3 and [entry.revision for entry in page.items] == [3, 2]
        assert all(entry.actor_id == ACTOR_ID and entry.origin == "replacement" and entry.object_count == 1
                   for entry in page.items)
        second_page = await svc.list_history(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), page=2, page_size=2)
        assert [entry.revision for entry in second_page.items] == [1] and second_page.total == 3
        beyond = await svc.list_history(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), page=3, page_size=2)
        assert beyond.total == 3 and beyond.items == []
        historical = await svc.get_revision(network_id=NETWORK_ID, revision=1, actor_user_id=str(ACTOR_ID))
        assert historical == first
        restored = await svc.replace_scene(
            network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), correlation_id="restore",
            req=ReplaceSpatialSceneRequest.model_validate({
                "expected_revision": 3, "scene": historical.model_dump(mode="json", exclude={"revision"}),
            }),
        )
        assert restored.revision == 4 and restored.objects == first.objects
        assert await svc.get_revision(network_id=NETWORK_ID, revision=1, actor_user_id=str(ACTOR_ID)) == first
        assert (await svc.list_history(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID))).total == 4


@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
async def test_history_database_mutation_is_rejected(sessions, operation):
    await replace(sessions)
    statements = {
        "update": update(SpatialSceneRevision).values(origin="baseline"),
        "delete": delete(SpatialSceneRevision),
        "truncate": text("TRUNCATE network_spatial_scene_revisions"),
    }
    async with sessions() as db:
        with pytest.raises(DBAPIError, match="spatial scene history is immutable"):
            await db.execute(statements[operation])
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(SpatialSceneRevision)) == 1


async def test_history_insert_failure_rolls_back_current_snapshot_before_audit(sessions, monkeypatch):
    before = await replace(sessions)
    original = SpatialSceneRepository.append_revision

    async def fail_after_history(self, *args):
        await original(self, *args)
        raise RuntimeError("history append failed")

    monkeypatch.setattr(SpatialSceneRepository, "append_revision", fail_after_history)
    with pytest.raises(RuntimeError, match="history append failed"):
        await replace(sessions, 1, [spatial_object("failed")])
    assert await read(sessions) == before
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SpatialSceneRevision)) == 1
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1


async def test_history_reads_refresh_revocation_and_enforce_tenant_scope(sessions):
    await replace(sessions)
    async with sessions() as reader:
        member = await reader.get(OrgMember, (ORG_ID, ACTOR_ID))
        svc = SpatialSceneService(reader, None)
        assert (await svc.list_history(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID))).total == 1
        for scope in ({"requested_workspace_id": uuid.UUID(int=999)}, {"claim_org_id": uuid.UUID(int=999)}):
            with pytest.raises(HTTPException) as error:
                await svc.get_revision(network_id=NETWORK_ID, revision=1, actor_user_id=str(ACTOR_ID), **scope)
            assert error.value.status_code == 403
        async with sessions() as revoker:
            await revoker.execute(update(OrgMember).where(OrgMember.org_id == ORG_ID).values(deleted_at=func.now()))
            await revoker.commit()
        assert member.deleted_at is None
        for call in (
            svc.list_history(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID)),
            svc.get_revision(network_id=NETWORK_ID, revision=999, actor_user_id=str(ACTOR_ID)),
        ):
            with pytest.raises(HTTPException) as error:
                await call
            assert error.value.status_code == 403


async def test_migration_preserves_existing_snapshot_as_single_baseline(sessions):
    original = await replace(sessions, objects=[spatial_object("original")])
    current = await replace(sessions, 1, [spatial_object("current")])

    def migrate(connection, target, down):
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        operation = scripts._downgrade_revs if down else scripts._upgrade_revs
        with EnvironmentContext(config, scripts, fn=lambda rev, _: operation(target, rev)) as context:
            context.configure(connection=connection)
            context.run_migrations()

    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(migrate, "0021", True)
        assert (await db.get(SpatialSceneRecord, NETWORK_ID)).revision == current.revision
        await connection.run_sync(migrate, "0022", False)
        await db.commit()
    async with sessions() as db:
        svc = SpatialSceneService(db, None)
        history = await svc.list_history(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID))
        assert history.total == 1 and history.items[0].revision == 2
        assert history.items[0].origin == "baseline" and history.items[0].actor_id is None
        assert await svc.get_revision(network_id=NETWORK_ID, revision=2, actor_user_id=str(ACTOR_ID)) == current
        with pytest.raises(HTTPException):
            await svc.get_revision(network_id=NETWORK_ID, revision=original.revision, actor_user_id=str(ACTOR_ID))
    assert (await replace(sessions, 2)).revision == 3


async def test_history_network_isolation_and_restore_revalidates_deleted_device(sessions):
    saved = await replace(sessions, objects=[spatial_object(device_id=str(DEVICE_ID))])
    other_network = uuid.UUID(int=502)
    async with sessions() as db:
        db.add(Network(network_id=other_network, workspace_id=WORKSPACE_ID, name="Other accessible network"))
        await db.execute(update(Device).where(Device.device_id == DEVICE_ID).values(deleted_at=func.now()))
        await db.commit()
    async with sessions() as db:
        svc = SpatialSceneService(db, None)
        # Same organization membership grants access, but never leaks another network's history.
        assert (await svc.list_history(network_id=other_network, actor_user_id=str(ACTOR_ID))).total == 0
        with pytest.raises(HTTPException) as error:
            await svc.get_revision(network_id=other_network, revision=1, actor_user_id=str(ACTOR_ID))
        assert error.value.detail["code"] == "SPATIAL_REVISION_NOT_FOUND"
        historical = await svc.get_revision(network_id=NETWORK_ID, revision=1, actor_user_id=str(ACTOR_ID))
        assert historical == saved
        with pytest.raises(HTTPException) as error:
            await svc.replace_scene(
                network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), correlation_id="invalid-restore",
                req=ReplaceSpatialSceneRequest.model_validate({
                    "expected_revision": 1, "scene": historical.model_dump(mode="json", exclude={"revision"}),
                }),
            )
        assert error.value.detail["code"] == "SPATIAL_DEVICE_SCOPE_INVALID"
        assert (await svc.list_history(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID))).total == 1
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1
