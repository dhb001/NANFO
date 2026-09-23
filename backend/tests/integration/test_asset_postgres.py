"""Real0023 migration/transactions, enabled only for an isolated ASSET_TEST_DSN."""

import asyncio
import os
import threading
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.network.asset_backfill import migrate_batch
from app.modules.network.asset_settings import AssetSettings
from app.modules.network.asset_storage import AssetIntegrityError, LocalAssetStore
from app.modules.network.models import CampusModelAssetRecord, Network
from app.modules.network.repository import CampusModelAssetRepository
from app.modules.network.service import CampusModelAssetService
from app.modules.organization.models import Organization, OrgMember, Workspace
from tests.asset_support import ACTOR_ID, NETWORK_ID, ORG_ID, WORKSPACE_ID, registration, request, row

pytestmark = pytest.mark.skipif(not os.environ.get("ASSET_TEST_DSN"), reason="ASSET_TEST_DSN not configured")


@pytest.fixture
async def database(tmp_path):
    schema = "asset_test_" + uuid.uuid4().hex
    url = make_url(os.environ["ASSET_TEST_DSN"])
    sync = create_engine(url.set(drivername="postgresql+psycopg2"))
    engine = None
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    def migrate(target, down=False):
        with sync.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration = scripts._downgrade_revs if down else scripts._upgrade_revs
            with EnvironmentContext(config, scripts, fn=lambda rev, _: migration(target, rev)) as ctx:
                ctx.configure(connection=connection)
                ctx.run_migrations()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == target

    with sync.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        migrate("0023")
        migrate("0022", down=True)
        migrate("0023")
        engine = create_async_engine(url.set(drivername="postgresql+asyncpg"),
                                     connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            db.add(Organization(org_id=ORG_ID, name="Assets", slug="assets"))
            await db.flush()
            db.add(Workspace(workspace_id=WORKSPACE_ID, org_id=ORG_ID, name="Assets"))
            db.add(OrgMember(org_id=ORG_ID, user_id=ACTOR_ID, org_role="Operator"))
            db.add(Network(network_id=NETWORK_ID, workspace_id=WORKSPACE_ID, name="Assets"))
            await db.commit()
        tmp_path.chmod(0o700)
        yield sessions, LocalAssetStore(AssetSettings(root=tmp_path)), migrate
    finally:
        if engine is not None:
            await engine.dispose()
        with sync.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        sync.dispose()


async def upload(database, **changes):
    sessions, store, _ = database
    async with sessions() as db:
        result = await CampusModelAssetService(db, None, asset_store=store).upsert_asset(
            network_id=NETWORK_ID, actor_id=str(ACTOR_ID), req=request(**changes),
        )
        return result.items[0]


async def test_metadata_paging_scoped_ordered_without_inline_or_cas_reads(database):
    sessions, store, _ = database
    timestamp = row().created_at
    foreign_network = uuid.uuid4()
    async with sessions() as db:
        db.add(Network(network_id=foreign_network, workspace_id=WORKSPACE_ID, name="Other"))
        await db.flush()
        for i in reversed(range(23)):
            db.add(row(campus_model_asset_id=uuid.UUID(int=i + 1), created_at=timestamp,
                       storage_backend="local_cas" if i % 2 else "inline",
                       model_data_base64=None if i % 2 else request().model_data_base64))
        db.add(row(network_id=foreign_network, created_at=timestamp))
        db.add(row(deleted_at=timestamp, created_at=timestamp))
        await db.commit()
    async with sessions() as db:
        svc = CampusModelAssetService(db, None, asset_store=store)
        pages = [await svc.list_assets(network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), include_data=False,
                                      page=page, page_size=10) for page in (1, 2, 3, 4)]
        assert [len(page.items) for page in pages] == [10, 10, 3, 0]
        assert all(page.total == 23 for page in pages)
        assert [item.campus_model_asset_id.int for page in pages for item in page.items] == list(range(1, 24))
        assert all("model_data_base64" not in item.model_dump() for page in pages for item in page.items)
        assert len((await CampusModelAssetRepository(db).list_metadata_for_network(NETWORK_ID, page=1, page_size=100))[0]) == 23


async def test_persist_reload_registration_and_immutable_identity(database):
    sessions, store, _ = database
    created = await upload(database, registration=registration())
    async with sessions() as db:
        stored = await db.get(CampusModelAssetRecord, created.campus_model_asset_id)
        assert stored.model_data_base64 is None and stored.storage_backend == "local_cas"
        assert stored.registration == registration()
        listed = await CampusModelAssetService(db, None, asset_store=store).list_assets(
            network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID),
        )
        assert listed.items == [created]
        with pytest.raises(DBAPIError):
            await db.execute(update(CampusModelAssetRecord).values(model_sha256="0" * 64))
        await db.rollback()
    same = await upload(database, replace_existing=False)
    assert same.campus_model_asset_id == created.campus_model_asset_id and same.registration == created.registration
    changed = await upload(database, body=b"new-model", replace_existing=False)
    assert changed.campus_model_asset_id != created.campus_model_asset_id
    assert changed.registration is None
    replaced = await upload(database)
    async with sessions() as db:
        rows = (await db.scalars(select(CampusModelAssetRecord))).all()
        assert len(rows) == 3
        assert all(r.deleted_at is not None for r in rows if r.campus_model_asset_id != replaced.campus_model_asset_id)
    assert len(list(store.settings.root.iterdir())) == 2


async def test_backfill_soft_deleted_reverse_and_downgrade_guard(database):
    sessions, store, migrate = database
    legacy = row(deleted_at=row().created_at)
    async with sessions() as db:
        db.add(legacy)
        await db.commit()
    async with sessions() as db:
        assert (await migrate_batch(db, store, direction="to-cas", limit=1))["processed"] == 1
    with pytest.raises(DBAPIError, match="Restore every asset inline"):
        migrate("0022", down=True)
    async with sessions() as db:
        saved = await db.get(CampusModelAssetRecord, legacy.campus_model_asset_id)
        assert saved.registration is None and saved.deleted_at is not None and saved.model_data_base64 is None
        assert (await migrate_batch(db, store, direction="to-cas", limit=1))["processed"] == 0
        assert (await migrate_batch(db, store, direction="to-inline", limit=1))["processed"] == 1
    migrate("0022", down=True)
    migrate("0023")
    async with sessions() as db:
        saved = await db.get(CampusModelAssetRecord, legacy.campus_model_asset_id)
        assert saved.model_data_base64 == request().model_data_base64 and saved.storage_backend == "inline"
    assert len(list(store.settings.root.iterdir())) == 1


async def test_commit_failure_rolls_back_metadata_retains_verified_object(database, monkeypatch):
    sessions, store, _ = database
    first = await upload(database)
    async with sessions() as db:
        async def fail():
            raise RuntimeError("injected commit failure")
        monkeypatch.setattr(db, "commit", fail)
        with pytest.raises(RuntimeError):
            await CampusModelAssetService(db, None, asset_store=store).upsert_asset(
                network_id=NETWORK_ID, actor_id=str(ACTOR_ID), req=request(b"new"),
            )
    async with sessions() as db:
        rows = (await db.scalars(select(CampusModelAssetRecord))).all()
        assert len(rows) == 1 and rows[0].campus_model_asset_id == first.campus_model_asset_id
        assert rows[0].deleted_at is None
    assert len(list(store.settings.root.iterdir())) == 2


async def test_current_membership_scope_download(database):
    sessions, store, _ = database
    created = await upload(database)
    async with sessions() as db:
        svc = CampusModelAssetService(db, None, asset_store=store)
        body, _ = await svc.download_asset(network_id=NETWORK_ID, asset_id=created.campus_model_asset_id,
                                           actor_user_id=str(ACTOR_ID))
        assert body == b"campus-model"
        with pytest.raises(HTTPException) as denial:
            await svc.download_asset(network_id=NETWORK_ID, asset_id=created.campus_model_asset_id,
                                     actor_user_id=str(ACTOR_ID), requested_workspace_id=uuid.uuid4())
        assert denial.value.status_code == 403
        await db.execute(update(OrgMember).values(deleted_at=created.created_at))
        await db.commit()
        with pytest.raises(HTTPException) as denial:
            await svc.download_asset(network_id=NETWORK_ID, asset_id=created.campus_model_asset_id,
                                     actor_user_id=str(ACTOR_ID))
        assert denial.value.status_code == 403


async def test_corrupt_backfill_batch_rolls_back_all_rows(database):
    sessions, store, _ = database
    first = row(campus_model_asset_id=uuid.UUID(int=1))
    corrupt = row(campus_model_asset_id=uuid.UUID(int=2), model_data_base64="dGFtcGVy")
    async with sessions() as db:
        db.add_all([first, corrupt])
        await db.commit()
    async with sessions() as db:
        with pytest.raises(AssetIntegrityError):
            await migrate_batch(db, store, direction="to-cas", limit=2)
    async with sessions() as db:
        rows = (await db.scalars(select(CampusModelAssetRecord))).all()
        assert all(r.storage_backend == "inline" and r.model_data_base64 is not None for r in rows)
    assert store.read(first.model_sha256, first.model_size_bytes) == b"campus-model"


async def test_current_authority_reloaded_after_network_lock_wait(database):
    sessions, store, _ = database
    async with sessions() as blocker, sessions() as writer:
        await blocker.execute(select(Network).where(Network.network_id == NETWORK_ID).with_for_update())
        writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
        # Deliberately retain stale membership in the writer's identity map.
        retained = (await writer.scalars(select(OrgMember))).one()
        task = asyncio.create_task(CampusModelAssetService(writer, None, asset_store=store).upsert_asset(
            network_id=NETWORK_ID, actor_id=str(ACTOR_ID), req=request(),
        ))
        try:
            async with sessions() as observer:
                for _ in range(200):
                    blocked = await observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid))"),
                                                    {"pid": writer_pid})
                    if blocked:
                        break
                    await asyncio.sleep(0.01)
                assert blocked, "writer never reached network row lock"
                await observer.execute(update(OrgMember).values(org_role="Read-Only"))
                await observer.commit()
            await blocker.commit()
            with pytest.raises(HTTPException) as denial:
                await asyncio.wait_for(task, 5)
            assert denial.value.status_code == 403
            assert retained is not None
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    async with sessions() as db:
        assert (await db.scalars(select(CampusModelAssetRecord))).all() == []
    assert list(store.settings.root.iterdir()) == []


@pytest.mark.parametrize("revocation", ["downgrade", "remove"])
async def test_revocation_during_final_response_read_rolls_back_replacement(database, monkeypatch, revocation):
    sessions, store, _ = database
    original = await upload(database)
    reached = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original_read = store.read

    def blocked_read(digest, size):
        loop.call_soon_threadsafe(reached.set)
        if not release.wait(10):
            raise RuntimeError("final response read was not released")
        return original_read(digest, size)

    monkeypatch.setattr(store, "read", blocked_read)
    async with sessions() as writer:
        retained = (await writer.scalars(select(OrgMember))).one()
        task = asyncio.create_task(CampusModelAssetService(writer, None, asset_store=store).upsert_asset(
            network_id=NETWORK_ID, actor_id=str(ACTOR_ID), req=request(b"replacement"),
        ))
        try:
            await asyncio.wait_for(reached.wait(), 5)
            async with sessions() as revoker:
                values = {"org_role": "Read-Only"} if revocation == "downgrade" else {"deleted_at": original.created_at}
                await revoker.execute(update(OrgMember).values(**values))
                await revoker.commit()
            assert retained.org_role == "Operator" and retained.deleted_at is None
            release.set()
            with pytest.raises(HTTPException) as denial:
                await asyncio.wait_for(task, 5)
            assert denial.value.status_code == 403
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with sessions() as db:
        rows = (await db.scalars(select(CampusModelAssetRecord))).all()
        assert len(rows) == 1 and rows[0].campus_model_asset_id == original.campus_model_asset_id
        assert rows[0].deleted_at is None
    assert original_read(request(b"replacement").model_sha256, len(b"replacement")) == b"replacement"
