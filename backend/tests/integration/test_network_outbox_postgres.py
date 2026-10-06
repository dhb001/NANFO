"""Opt-in disposable-schema PostgreSQL acceptance; never connects by default.

NETWORK_OUTBOX_TEST_DSN must explicitly name an isolated test PostgreSQL database.
Redis is in-memory. No Docker or physical network operations are performed here.
"""

import asyncio
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.network.models import Network
from app.modules.network.outbox import NetworkOutboxPublisher, NetworkOutboxRepository
from app.modules.network.outbox_models import NetworkOutbox
from app.modules.network.schemas import CreateNetworkRequest
from app.modules.network.service import NetworkService

pytestmark = pytest.mark.skipif(
    not os.environ.get("NETWORK_OUTBOX_TEST_DSN"), reason="NETWORK_OUTBOX_TEST_DSN not configured",
)
NETWORK = uuid.UUID(int=1)


@pytest.fixture
async def sessions(request):
    schema = "network_outbox_test_" + uuid.uuid4().hex
    url = make_url(os.environ["NETWORK_OUTBOX_TEST_DSN"])
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
            final_revision = getattr(request, "param", "0020")
            for target, direction in [("0020", "upgrade"), ("0019", "downgrade"), (final_revision, "upgrade")]:
                revisions = getattr(scripts, f"_{direction}_revs")
                with EnvironmentContext(
                    config, scripts,
                    fn=lambda rev, _, revisions=revisions, target=target: revisions(target, rev),
                ) as context:
                    context.configure(connection=connection)
                    context.run_migrations()
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == target
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


async def enqueue(sessions, network_id=NETWORK):
    async with sessions() as db:
        repo = NetworkOutboxRepository(db)
        await repo.lock_inventory(network_id)
        row = await repo.enqueue(network_id=network_id, event_type="network.device.updated",
                                 payload={"network_id": str(network_id)}, correlation_id=str(uuid.UUID(int=2)))
        await db.commit()
        return row


async def claim(sessions):
    async with sessions() as db:
        return await NetworkOutboxRepository(db).claim(lease_seconds=30)


async def test_inventory_and_outbox_commit_or_rollback_together(sessions):
    async def create(fail):
        async with sessions() as db:
            service = NetworkService(db, None)
            service._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=None))
            original = NetworkOutboxRepository.enqueue

            async def append_then_fail(repo, **kwargs):
                await original(repo, **kwargs)
                raise RuntimeError("after outbox flush")

            req = CreateNetworkRequest(workspace_id=uuid.UUID(int=3), name="atomic")
            if fail:
                with patch.object(NetworkOutboxRepository, "enqueue", append_then_fail):
                    await service.create_network(req, str(uuid.UUID(int=4)), str(uuid.UUID(int=5)))
            else:
                return await service.create_network(req, str(uuid.UUID(int=4)), str(uuid.UUID(int=5)))

    with pytest.raises(RuntimeError, match="after outbox flush"):
        await create(True)
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Network)) == 0
        assert await db.scalar(select(func.count()).select_from(NetworkOutbox)) == 0
    network = await create(False)
    async with sessions() as db:
        assert await db.get(Network, network.network_id) is not None
        row = (await db.scalars(select(NetworkOutbox))).one()
        assert row.network_id == network.network_id and row.published_at is None


async def test_concurrent_claims_ordering_expiry_and_stale_fencing(sessions):
    first = await enqueue(sessions)
    second = await enqueue(sessions)
    other = await enqueue(sessions, uuid.UUID(int=9))
    claims = await asyncio.wait_for(asyncio.gather(claim(sessions), claim(sessions)), 10)
    assert {c.event_id for c in claims} == {first.event_id, other.event_id}
    assert await claim(sessions) is None  # second is blocked by first, even while leased
    old = next(c for c in claims if c.event_id == first.event_id)
    async with sessions() as db:
        await db.execute(update(NetworkOutbox).where(NetworkOutbox.event_id == first.event_id).values(
            lease_until=func.now() - timedelta(seconds=1),
        ))
        await db.commit()
    replacement = await claim(sessions)
    assert replacement.event_id == old.event_id
    assert replacement.lease_token != old.lease_token
    async with sessions() as db:
        repo = NetworkOutboxRepository(db)
        assert not await repo.acknowledge(old)
        assert not await repo.defer(old, delay_seconds=1, error="stale")
        assert await repo.acknowledge(replacement)
    assert (await claim(sessions)).event_id == second.event_id


async def test_lost_ack_restart_replays_identical_wire_event(sessions, fake_redis):
    row = await enqueue(sessions)
    publisher = NetworkOutboxPublisher(sessions=sessions, redis=fake_redis)
    with (
        patch.object(NetworkOutboxRepository, "acknowledge", AsyncMock(side_effect=RuntimeError("lost ack"))),
        pytest.raises(RuntimeError, match="lost ack"),
    ):
        await publisher.publish_one()
    assert await publisher.drain() == 0
    async with sessions() as db:
        await db.execute(update(NetworkOutbox).values(lease_until=func.now() - timedelta(seconds=1)))
        await db.commit()
    assert await NetworkOutboxPublisher(sessions=sessions, redis=fake_redis).drain() == 1
    entries = await fake_redis.xrange("stream:network")
    assert len(entries) == 2 and entries[0][1] == entries[1][1] == row.envelope
    async with sessions() as db:
        stored = await db.get(NetworkOutbox, row.event_id)
        assert stored.published_at is not None and stored.attempts == 2 and stored.lease_token is None


async def test_retry_due_time_blocks_same_network_but_not_other_networks(sessions):
    first = await enqueue(sessions)
    await enqueue(sessions)
    current = await claim(sessions)
    async with sessions() as db:
        assert await NetworkOutboxRepository(db).defer(current, delay_seconds=300, error="ConnectionError")
    other = await enqueue(sessions, uuid.UUID(int=9))
    assert (await claim(sessions)).event_id == other.event_id
    assert await claim(sessions) is None
    async with sessions() as db:
        await db.execute(update(NetworkOutbox).where(NetworkOutbox.event_id == first.event_id).values(
            next_attempt_at=func.now() - timedelta(seconds=1),
        ))
        await db.commit()
    assert (await claim(sessions)).event_id == first.event_id


# Current services append scene history (0022+); retain the fixture's0020→0019
# roundtrip before upgrading to the current repository schema for this interop case.
@pytest.mark.parametrize("sessions", ["0028"], indirect=True)
@pytest.mark.parametrize("first_writer", ["spatial", "inventory"])
async def test_spatial_and_inventory_locks_complete_without_deadlock(sessions, monkeypatch, first_writer):
    """Force each real row-lock wait; preserve scene/audit and inventory/event atomically."""
    from app.modules.identity.models import AuditLog
    from app.modules.network.models import Device
    from app.modules.network.service import DeviceService
    from app.modules.network.schemas import UpdateDeviceRequest
    from app.modules.network.spatial_models import SpatialSceneRecord
    from app.modules.network.spatial_repository import SpatialSceneRepository
    from app.modules.network.spatial_schemas import ReplaceSpatialSceneRequest
    from app.modules.network.spatial_service import SpatialSceneService
    from app.modules.organization.models import Organization, OrgMember, Workspace
    from tests.spatial_support import replace_payload, spatial_object

    workspace, org, actor, device_id = (uuid.UUID(int=n) for n in (20, 21, 22, 23))
    async with sessions() as db:
        db.add(Organization(org_id=org, name="Outbox Interop", slug="outbox-interop"))
        await db.flush()
        db.add(Workspace(workspace_id=workspace, org_id=org, name="Outbox Interop"))
        db.add(OrgMember(org_id=org, user_id=actor, org_role="Operator"))
        db.add(Network(network_id=NETWORK, workspace_id=workspace, name="Outbox Interop"))
        await db.flush()
        db.add(Device(device_id=device_id, network_id=NETWORK, hostname="interop", device_type="ap",
                      spatial_ref_id="before"))
        await db.commit()

    held, release = asyncio.Event(), asyncio.Event()
    ready = {name: asyncio.Event() for name in ("spatial", "inventory")}
    pids = {}
    original_scope = SpatialSceneRepository.active_device_ids
    original_enqueue = NetworkOutboxRepository.enqueue

    async def hold_spatial(repo, *args, **kwargs):
        result = await original_scope(repo, *args, **kwargs)
        if first_writer == "spatial":
            held.set()
            await release.wait()
        return result

    async def hold_inventory(repo, **kwargs):
        result = await original_enqueue(repo, **kwargs)
        if first_writer == "inventory":
            held.set()
            await release.wait()
        return result

    monkeypatch.setattr(SpatialSceneRepository, "active_device_ids", hold_spatial)
    monkeypatch.setattr(NetworkOutboxRepository, "enqueue", hold_inventory)

    async def writer(name):
        async with sessions() as db:
            pids[name] = await db.scalar(select(func.pg_backend_pid()))
            ready[name].set()
            if name == "inventory":
                return await DeviceService(db, None).update_device_spatial_ref(
                    NETWORK, device_id, UpdateDeviceRequest(spatial_ref_id="after"), str(actor), "interop",
                )
            return await SpatialSceneService(db, None).replace_scene(
                network_id=NETWORK, actor_user_id=str(actor), correlation_id="interop",
                req=ReplaceSpatialSceneRequest.model_validate(replace_payload(
                    objects=[spatial_object(device_id=str(device_id))],
                )),
            )

    second_writer = "inventory" if first_writer == "spatial" else "spatial"
    tasks = [asyncio.create_task(writer(first_writer))]
    try:
        await asyncio.wait_for(held.wait(), 5)
        tasks.append(asyncio.create_task(writer(second_writer)))
        await asyncio.wait_for(ready[second_writer].wait(), 5)
        # Verify actual PostgreSQL blocking, rather than assuming a sleep forced overlap.
        async with asyncio.timeout(5), sessions() as observer:
            while True:
                blockers = await observer.scalar(select(func.pg_blocking_pids(pids[second_writer])))
                if pids[first_writer] in blockers:
                    break
                await asyncio.sleep(0.01)
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async with sessions() as db:
        assert (await db.get(Device, device_id)).spatial_ref_id == "after"
        scene = await db.get(SpatialSceneRecord, NETWORK)
        assert scene.revision == 1 and scene.scene["objects"][0]["device_id"] == str(device_id)
        audit = (await db.scalars(select(AuditLog))).one()
        assert audit.event_type == "network.spatial_scene.replaced"
        event = (await db.scalars(select(NetworkOutbox))).one()
        assert event.envelope["event_type"] == "network.device.updated"
        assert json.loads(event.envelope["payload"])["changed_fields"] == {"spatial_ref_id": "after"}
        assert event.published_at is None


async def test_payload_carries_the_committed_outbox_sequence_in_network_order(sessions):
    """C13: consumers order by (network_id, sequence); payload value equals the row identity."""
    rows = [await enqueue(sessions), await enqueue(sessions, uuid.UUID(int=9)), await enqueue(sessions)]
    async with sessions() as db:
        stored = {row.event_id: row for row in (await db.scalars(select(NetworkOutbox))).all()}
        watermark = await NetworkOutboxRepository(db).watermark()
    sequences = [json.loads(stored[row.event_id].envelope["payload"])["sequence"] for row in rows]
    assert sequences == [stored[row.event_id].sequence for row in rows]
    assert sequences == sorted(sequences) and len(set(sequences)) == 3
    assert watermark == max(sequences)
    later = await enqueue(sessions)
    assert later.sequence > watermark


async def test_retention_deletes_only_old_published_rows_and_keeps_the_watermark_anchor(sessions, fake_redis):
    """Persistence F18: bounded batch deletes; unpublished rows and the newest row survive."""
    rows = [await enqueue(sessions) for _ in range(5)]
    async with sessions() as db:
        await db.execute(update(NetworkOutbox).where(
            NetworkOutbox.event_id.in_([rows[0].event_id, rows[1].event_id, rows[4].event_id]),
        ).values(published_at=func.now() - timedelta(days=40)))
        await db.execute(update(NetworkOutbox).where(NetworkOutbox.event_id == rows[3].event_id)
                         .values(published_at=func.now() - timedelta(days=1)))
        # rows[2] stays unpublished even though it is old.
        await db.execute(update(NetworkOutbox).where(NetworkOutbox.event_id == rows[2].event_id)
                         .values(created_at=func.now() - timedelta(days=90)))
        await db.commit()
        watermark = await NetworkOutboxRepository(db).watermark()
    clock = [100.0]
    publisher = NetworkOutboxPublisher(sessions=sessions, redis=fake_redis, retention_days=30,
                                       retention_batch=1, clock=lambda: clock[0])
    assert await publisher.purge_published() == 1
    assert await publisher.purge_published() == 1  # a full batch schedules the next one immediately
    assert await publisher.purge_published() == 0  # rows[4] is old but anchors the watermark
    assert await publisher.purge_published() == 0  # rate limited until the next interval
    async with sessions() as db:
        remaining = set((await db.scalars(select(NetworkOutbox.event_id))).all())
        assert remaining == {rows[2].event_id, rows[3].event_id, rows[4].event_id}
        assert await NetworkOutboxRepository(db).watermark() == watermark
    # The regular loop keeps publishing the pending row after retention ran.
    assert await publisher.drain(limit=5) == 1
    async with sessions() as db:
        assert (await db.get(NetworkOutbox, rows[2].event_id)).published_at is not None
