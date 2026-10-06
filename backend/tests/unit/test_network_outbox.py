"""Offline fault injection for inventory atomicity, stable replay and worker bounds."""

import asyncio
import importlib.util
import io
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql

from app.events.bus import process_entry
from app.modules.network.outbox import NetworkOutboxPublisher, NetworkOutboxRepository, OutboxClaim
from app.modules.network.outbox_models import NetworkOutbox
from app.modules.network.schemas import CreateDeviceRequest, CreateNetworkRequest, UpdateDeviceRequest
from app.modules.network.service import DeviceService, NetworkService

NETWORK = uuid.UUID(int=1)
WORKSPACE = uuid.UUID(int=2)
DEVICE = uuid.UUID(int=3)
ACTOR = str(uuid.UUID(int=4))
CORRELATION = str(uuid.UUID(int=5))


def claim(attempts=1):
    event_id = uuid.UUID(int=6)
    return OutboxClaim(event_id, uuid.UUID(int=7), {
        "event_id": str(event_id), "event_type": "network.device.added",
        "timestamp": "2026-09-19T10:00:00+00:00", "source": "network",
        "version": "1", "correlation_id": CORRELATION,
        "payload": json.dumps({"network_id": str(NETWORK), "device_id": str(DEVICE)}),
    }, attempts)


@pytest.fixture
def sessions(mock_db):
    @asynccontextmanager
    async def factory():
        yield mock_db
    return factory


@pytest.mark.parametrize("operation", ["network", "device", "update"])
@pytest.mark.parametrize("fail_commit", [False, True])
async def test_mutation_and_event_share_commit_without_redis(mock_db, operation, fail_commit):
    network = SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE, name="Fixture",
                              description=None, cidr=None, created_at=datetime.now(UTC))
    device = SimpleNamespace(device_id=DEVICE, network_id=NETWORK, hostname="fixture",
                             ip_address=None, device_type="switch", spatial_ref_id="before",
                             vendor=None, model=None, location_hint=None, status="active",
                             created_at=datetime.now(UTC))
    redis = AsyncMock()
    redis.xadd.side_effect = ConnectionError("Redis must not be used in mutation")
    if operation == "network":
        svc = NetworkService(mock_db, redis)
        svc._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=None))
        svc._repo.create = AsyncMock(return_value=network)
        mutate = lambda: svc.create_network(  # noqa: E731
            CreateNetworkRequest(workspace_id=WORKSPACE, name="Fixture"), ACTOR, CORRELATION,
        )
        expected_type = "network.network.created"
    else:
        svc = DeviceService(mock_db, redis)
        svc._network_repo.get_by_id = AsyncMock(return_value=network)
        svc._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=WORKSPACE))
        if operation == "device":
            svc._repo.create = AsyncMock(return_value=device)
            mutate = lambda: svc.add_device(  # noqa: E731
                NETWORK, CreateDeviceRequest(hostname="fixture", device_type="switch"), ACTOR, CORRELATION,
            )
            expected_type = "network.device.added"
        else:
            svc._repo.get_by_id = AsyncMock(return_value=device)

            async def update(current, fields):
                device.spatial_ref_id = fields["spatial_ref_id"]
                return device

            svc._repo.update = AsyncMock(side_effect=update)
            mutate = lambda: svc.update_device_spatial_ref(  # noqa: E731
                NETWORK, DEVICE, UpdateDeviceRequest(spatial_ref_id="after"), ACTOR, CORRELATION,
            )
            expected_type = "network.device.updated"

    async def commit():
        row = mock_db.add.call_args.args[0]
        assert isinstance(row, NetworkOutbox)
        assert row.network_id == NETWORK
        assert row.envelope["event_type"] == expected_type
        assert row.envelope["correlation_id"] == CORRELATION
        assert json.loads(row.envelope["payload"])["actor_id"] == ACTOR
        mock_db.flush.assert_awaited_once()
        if fail_commit:
            raise RuntimeError("commit rejected")

    mock_db.commit.side_effect = commit
    if fail_commit:
        with pytest.raises(RuntimeError, match="commit rejected"):
            await mutate()
        mock_db.rollback.assert_awaited_once()
        mock_db.refresh.assert_not_awaited()
    else:
        await mutate()
        mock_db.commit.assert_awaited_once()
        mock_db.rollback.assert_not_awaited()
    redis.xadd.assert_not_awaited()


async def test_enqueue_snapshots_payload_and_rejects_undocumented_event(mock_db):
    repo = NetworkOutboxRepository(mock_db)
    mock_db.scalar.return_value = 41
    payload = {"nested": {"value": 1}}
    row = await repo.enqueue(network_id=NETWORK, event_type="network.device.updated",
                             payload=payload, correlation_id=CORRELATION)
    payload["nested"]["value"] = 2
    # C13: the durable per-network outbox sequence is part of the wire payload.
    assert json.loads(row.envelope["payload"]) == {"nested": {"value": 1}, "sequence": 41}
    assert row.sequence == 41
    allocation = str(mock_db.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "nextval(pg_get_serial_sequence(" in allocation
    assert row.envelope["event_id"] == str(row.event_id)
    assert datetime.fromisoformat(row.envelope["timestamp"]).tzinfo is not None
    mock_db.commit.assert_not_awaited()
    with pytest.raises(ValueError, match="Undocumented"):
        await repo.enqueue(network_id=NETWORK, event_type="network.group.created",
                           payload={}, correlation_id=CORRELATION)


async def test_payload_sequence_is_authoritative_and_watermark_is_committed_max(mock_db):
    repo = NetworkOutboxRepository(mock_db)
    mock_db.scalar.return_value = 7
    row = await repo.enqueue(network_id=NETWORK, event_type="network.device.deleted",
                             payload={"device_id": str(DEVICE), "sequence": 1}, correlation_id=CORRELATION)
    assert json.loads(row.envelope["payload"])["sequence"] == 7
    mock_db.scalar.return_value = None
    assert await repo.watermark() == 0
    statement = str(mock_db.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "max(network_outbox.sequence)" in statement


async def test_claim_uses_skip_locked_expiry_and_per_network_predecessor(mock_db):
    row = NetworkOutbox(event_id=claim().event_id, envelope=claim().envelope, attempts=2)
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    mock_db.execute.return_value = result
    claimed = await NetworkOutboxRepository(mock_db).claim(lease_seconds=30)
    sql = str(mock_db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "network_outbox.lease_until <= now()" in sql
    assert "network_outbox_1.sequence < network_outbox.sequence" in sql
    assert "network_outbox_1.network_id = network_outbox.network_id" in sql
    assert "network_outbox_1.published_at IS NULL" in sql
    assert claimed.attempts == 3 and row.lease_token == claimed.lease_token
    assert claimed.envelope == claim().envelope
    mock_db.commit.assert_awaited_once()


@pytest.mark.parametrize("action", ["acknowledge", "defer"])
async def test_stale_lease_cannot_mark_publication_or_release_new_owner(mock_db, action):
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result
    repo = NetworkOutboxRepository(mock_db)
    args = {"delay_seconds": 5, "error": "ConnectionError"} if action == "defer" else {}
    assert await getattr(repo, action)(claim(), **args) is False
    statement = mock_db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(statement)
    assert "network_outbox.lease_token =" in sql
    assert "network_outbox.lease_until > now()" in sql
    assert "network_outbox.published_at IS NULL" in sql
    assert claim().lease_token in statement.params.values()


async def test_lost_database_ack_replays_identical_envelope_and_bus_deduplicates(sessions, fake_redis):
    publisher = NetworkOutboxPublisher(sessions=sessions, redis=fake_redis)
    with (
        patch.object(NetworkOutboxRepository, "claim", AsyncMock(return_value=claim())),
        patch.object(NetworkOutboxRepository, "acknowledge", AsyncMock(
            side_effect=[RuntimeError("lost database ack"), True],
        )),
    ):
        with pytest.raises(RuntimeError, match="lost database ack"):
            await publisher.publish_one()
        assert await publisher.publish_one()
    entries = await fake_redis.xrange("stream:network")
    assert len(entries) == 2
    assert entries[0][1] == entries[1][1] == claim().envelope
    received = []

    async def consumer(event):
        received.append(event)

    await fake_redis.xgroup_create("stream:network", "fixture", id="0")
    for entry_id, fields in entries:
        await process_entry(fake_redis, "stream:network", "fixture", entry_id, fields,
                            {"network.device.added": consumer})
    assert len(received) == 1
    assert received[0]["timestamp"] == claim().envelope["timestamp"]


@pytest.mark.parametrize("attempts,delay", [(1, 1), (2, 2), (15, 300), (1000, 300)])
async def test_redis_failure_retries_with_capped_backoff_and_sanitized_error(sessions, attempts, delay):
    redis = AsyncMock()
    redis.xadd.side_effect = ConnectionError("redis://secret@host")
    publisher = NetworkOutboxPublisher(sessions=sessions, redis=redis)
    with (
        patch.object(NetworkOutboxRepository, "claim", AsyncMock(return_value=claim(attempts))),
        patch.object(NetworkOutboxRepository, "defer", AsyncMock(return_value=True)) as defer,
        patch.object(NetworkOutboxRepository, "acknowledge", AsyncMock()) as ack,
        pytest.raises(ConnectionError),
    ):
        await publisher.publish_one()
    defer.assert_awaited_once_with(claim(attempts), delay_seconds=delay, error="ConnectionError")
    ack.assert_not_awaited()


async def test_cancelled_publication_leaves_lease_for_recovery(sessions):
    redis = AsyncMock()
    redis.xadd.side_effect = asyncio.CancelledError
    with (
        patch.object(NetworkOutboxRepository, "claim", AsyncMock(return_value=claim())),
        patch.object(NetworkOutboxRepository, "defer", AsyncMock()) as defer,
        patch.object(NetworkOutboxRepository, "acknowledge", AsyncMock()) as ack,
        pytest.raises(asyncio.CancelledError),
    ):
        await NetworkOutboxPublisher(sessions=sessions, redis=redis).publish_one()
    defer.assert_not_awaited()
    ack.assert_not_awaited()


async def test_slow_redis_is_bounded_and_deferred(sessions):
    async def hang(*args):
        await asyncio.Event().wait()

    redis = SimpleNamespace(xadd=hang)
    with (
        patch.object(NetworkOutboxRepository, "claim", AsyncMock(return_value=claim())),
        patch.object(NetworkOutboxRepository, "defer", AsyncMock(return_value=True)) as defer,
        pytest.raises(TimeoutError),
    ):
        await NetworkOutboxPublisher(sessions=sessions, redis=redis, publish_timeout=0.01).publish_one()
    assert defer.await_args.kwargs["error"] == "TimeoutError"


async def test_batch_limit_and_empty_poll(sessions):
    publisher = NetworkOutboxPublisher(sessions=sessions, redis=AsyncMock())
    with patch.object(publisher, "publish_one", AsyncMock(return_value=True)) as publish:
        assert await publisher.drain(limit=3) == 3
        assert publish.await_count == 3
    with patch.object(publisher, "publish_one", AsyncMock(return_value=False)) as publish:
        assert await publisher.drain(limit=3) == 0
        publish.assert_awaited_once()
    with pytest.raises(ValueError):
        await publisher.drain(limit=0)


@pytest.mark.parametrize("options", [
    {"lease_seconds": 5}, {"publish_timeout": 0}, {"retry_base_seconds": 301},
    {"lease_seconds": float("inf")}, {"retry_max_seconds": float("nan")},
])
def test_invalid_worker_bounds(sessions, options):
    with pytest.raises(ValueError):
        NetworkOutboxPublisher(sessions=sessions, redis=None, **options)


def test_migration_generates_postgresql_ddl_without_connection():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0020_network_inventory_outbox.py"
    spec = importlib.util.spec_from_file_location("network_outbox_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert (migration.revision, migration.down_revision) == ("0020", "0019")
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={
        "as_sql": True, "output_buffer": output,
    })
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "CREATE TABLE network_outbox" in sql
    assert "GENERATED BY DEFAULT AS IDENTITY" in sql
    assert "envelope JSONB NOT NULL" in sql
    assert "WHERE published_at IS NULL" in sql
    assert "DROP TABLE network_outbox" in sql


# ---------------------------------------------------------------- retention (F18)


async def test_purge_statement_is_bounded_published_only_and_keeps_the_newest_row(mock_db):
    from datetime import timedelta

    mock_db.scalar = AsyncMock(return_value=7)
    assert await NetworkOutboxRepository(mock_db).purge_published(older_than=timedelta(days=30), limit=500) == 7
    compiled = mock_db.scalar.await_args.args[0].compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).split())
    assert sql.startswith("WITH purged AS (DELETE FROM network_outbox WHERE network_outbox.event_id IN (SELECT")
    assert "network_outbox.published_at IS NOT NULL" in sql
    assert "network_outbox.published_at < now() -" in sql
    assert "network_outbox.sequence < (SELECT max(network_outbox.sequence)" in sql
    assert "ORDER BY network_outbox.sequence LIMIT" in sql and "FOR UPDATE SKIP LOCKED" in sql
    assert compiled.params["param_1"] == 500 and timedelta(days=30) in compiled.params.values()
    for bad in ({"older_than": timedelta(0), "limit": 1}, {"older_than": timedelta(days=1), "limit": 0},
                {"older_than": timedelta(days=1), "limit": True}):
        with pytest.raises(ValueError):
            await NetworkOutboxRepository(mock_db).purge_published(**bad)


def retention_publisher(sessions, clock, **kwargs):
    return NetworkOutboxPublisher(sessions=sessions, redis=AsyncMock(), clock=lambda: clock[0], **kwargs)


async def test_drain_applies_one_retention_batch_per_interval(sessions, mock_db):
    clock = [1000.0]
    publisher = retention_publisher(sessions, clock, retention_days=30, retention_batch=100)
    with (
        patch.object(NetworkOutboxRepository, "purge_published", AsyncMock(return_value=3)) as purge,
        patch.object(publisher, "publish_one", AsyncMock(return_value=False)),
    ):
        await publisher.drain()
        await publisher.drain()
        assert purge.await_count == 1
        from datetime import timedelta
        assert purge.await_args.kwargs == {"older_than": timedelta(days=30), "limit": 100}
        clock[0] += 60
        await publisher.drain()
        assert purge.await_count == 2
    mock_db.commit.assert_awaited()


async def test_full_retention_batch_continues_on_the_next_iteration(sessions):
    clock = [0.0]
    publisher = retention_publisher(sessions, clock, retention_days=7, retention_batch=2)
    with patch.object(NetworkOutboxRepository, "purge_published", AsyncMock(side_effect=[2, 2, 1, 0])) as purge:
        assert [await publisher.purge_published() for _ in range(4)] == [2, 2, 1, 0]
        # Backlog drained in bounded batches; after a partial batch the interval applies.
        assert purge.await_count == 3


async def test_retention_failure_never_stops_publication(sessions, mock_db):
    publisher = retention_publisher(sessions, [0.0], retention_days=30)
    with (
        patch.object(NetworkOutboxRepository, "purge_published", AsyncMock(side_effect=RuntimeError("db"))),
        patch.object(publisher, "publish_one", AsyncMock(side_effect=[True, False])) as publish,
    ):
        assert await publisher.drain(limit=5) == 1
    assert publish.await_count == 2
    mock_db.rollback.assert_awaited()


@pytest.mark.parametrize("setting,expected", [(None, 30), (45, 45), (0, None), (-1, None), (True, None),
                                              ("30", None), (10**6, None)])
def test_retention_days_setting(sessions, setting, expected):
    from app.modules.network import outbox

    settings = SimpleNamespace() if setting is None else SimpleNamespace(NETWORK_OUTBOX_RETENTION_DAYS=setting)
    with patch("app.core.config.get_settings", return_value=settings):
        assert outbox.configured_retention_days() == expected
        assert NetworkOutboxPublisher(sessions=sessions, redis=None)._retention_days == expected


async def test_disabled_retention_never_deletes(sessions):
    publisher = retention_publisher(sessions, [0.0], retention_days=None)
    with patch.object(NetworkOutboxRepository, "purge_published", AsyncMock()) as purge:
        assert await publisher.purge_published() == 0
    purge.assert_not_awaited()
    with pytest.raises(ValueError):
        retention_publisher(sessions, [0.0], retention_days=0)


async def test_redis_memory_pressure_leaves_rows_unclaimed(sessions):
    from app.core.errors import DependencyUnavailableError

    publisher = retention_publisher(sessions, [0.0], retention_days=None)
    with (
        patch("app.modules.network.outbox.admit_publication",
              AsyncMock(side_effect=DependencyUnavailableError("redis"))),
        patch.object(NetworkOutboxRepository, "claim", AsyncMock()) as claimed,
        pytest.raises(DependencyUnavailableError),
    ):
        await publisher.drain()
    claimed.assert_not_awaited()
