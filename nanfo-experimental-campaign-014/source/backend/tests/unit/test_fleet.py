"""Fleet failure semantics with injected owning boundaries (no device/network I/O)."""

import asyncio
import copy
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.telemetry.fleet import FleetWorker
from app.modules.telemetry.fleet_config import FleetManifest, FleetSettings
from app.modules.telemetry.snmp_config import SNMPError, load_protected_json
from app.modules.telemetry.snmp_transport import InterfaceCounters


def protected(path, data):
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return path


@pytest.fixture
def config(tmp_path):
    targets = []
    for number in (1, 2):
        device = str(uuid.UUID(int=number))
        binding = protected(tmp_path / f"binding{number}.json", {
            "version": 1, "device_id": device, "org_id": str(uuid.UUID(int=3)),
            "workspace_id": str(uuid.UUID(int=4)), "network_id": str(uuid.UUID(int=5)),
            "actor_user_id": str(uuid.UUID(int=6)), "target": "127.0.0.1", "port": 20160 + number,
            "sys_name": "test", "interfaces": [{"if_index": 1, "if_name": "lo"}],
            "execution_mode": "emulation", "environment": "emulation",
        })
        credentials = protected(tmp_path / f"secret{number}.json", {
            "username": "test", "auth_passphrase": "test-auth-only", "priv_passphrase": "test-priv-only",
        })
        targets.append({"device_id": device, "binding_path": str(binding), "credentials_path": str(credentials),
                        "interval_seconds": 1.0, "backoff_max_seconds": 5.0})
    manifest = protected(tmp_path / "manifest.json", {"version": 1, "targets": targets})
    return FleetSettings(manifest_path=manifest, concurrency=2)


class MemoryRepository:
    def __init__(self):
        self.batches = {}
        self.outcomes = []

    async def pending(self, lease):
        batch = self.batches.get(lease.device_id)
        return copy.deepcopy(batch) if batch and batch.status == "pending" else None

    async def stage(self, lease, *, digest, samples, expires_at):
        batch = SimpleNamespace(batch_id=uuid.uuid4(), binding_sha256=digest, samples=samples,
                                expires_at=expires_at, cursor=0, status="pending")
        self.batches[lease.device_id] = batch
        return copy.deepcopy(batch)

    async def ready(self, lease, batch_id, digest):
        batch = self.batches[lease.device_id]
        assert batch.batch_id == batch_id
        if batch.status == "pending":
            if batch.expires_at <= datetime.now(UTC):
                batch.status = "expired"
            elif batch.binding_sha256 != digest:
                batch.status = "binding_changed"
        return copy.deepcopy(batch)

    async def acknowledge(self, lease, batch_id, cursor):
        batch = self.batches[lease.device_id]
        assert batch.batch_id == batch_id and batch.cursor == cursor
        batch.cursor += 1
        if batch.cursor == len(batch.samples):
            batch.status = "published"

    async def finish(self, lease, **kwargs):
        self.outcomes.append((lease.device_id, kwargs))


class MemoryLocks:
    def __init__(self):
        self.check = AsyncMock()
        self.held = set()

    @asynccontextmanager
    async def acquire(self, device_id, owner_id):
        if device_id in self.held:
            yield None
            return
        self.held.add(device_id)
        try:
            yield SimpleNamespace(device_id=device_id), self.check
        finally:
            self.held.remove(device_id)


def worker(config, *, repository=None, locks=None, authority=None, transport=None, ingestion=None):
    repository = repository or MemoryRepository()
    locks = locks or MemoryLocks()
    authority = authority or AsyncMock()
    transport = transport or SimpleNamespace(
        check_available=lambda: None,
        get=AsyncMock(return_value=InterfaceCounters(1000, 1, 12345, 23456, 1000000000, 0, ".1.2.3")),
    )
    ingestion = ingestion or SimpleNamespace(ingest=AsyncMock())
    instance = FleetWorker(settings=config, execution_mode="emulation", repository=repository, locks=locks,
                           sessions=None, redis=SimpleNamespace(set=AsyncMock()), ingestion=ingestion,
                           transport_factory=lambda **_: transport,
                           boundary_factory=lambda **_: SimpleNamespace(authorize=authority))
    return instance, repository, locks, authority, transport, ingestion


def test_manifest_protection_and_duplicate_devices(config):
    manifest = load_protected_json(config.manifest_path, FleetManifest)
    data = manifest.model_dump(mode="json")
    data["targets"].append(data["targets"][0])
    protected(config.manifest_path, data)
    with pytest.raises(SNMPError):
        load_protected_json(config.manifest_path, FleetManifest)
    config.manifest_path.chmod(0o644)
    with pytest.raises(SNMPError):
        load_protected_json(config.manifest_path, FleetManifest)


async def test_spool_commits_before_first_publish_and_restarts_with_exact_ids(config):
    first, repo, _, _, transport, ingestion = worker(config)
    target = first.manifest.targets[0]
    seen = []

    async def publish(**kwargs):
        batch = repo.batches[target.device_id]
        assert batch.status == "pending"
        assert kwargs["event_id"] in {sample["event_id"] for sample in batch.samples}
        seen.append(kwargs)
        raise ConnectionError("ambiguous send")

    ingestion.ingest.side_effect = publish
    assert await first.collect_target(target) == "collection_deferred"
    assert transport.get.await_count == 1
    second, _, _, _, new_transport, replay = worker(config, repository=repo)
    assert await second.collect_target(target) == "published"
    new_transport.get.assert_not_awaited()
    assert replay.ingest.call_args_list[0].kwargs == seen[0]
    assert len({call.kwargs["event_id"] for call in replay.ingest.call_args_list}) == 3


async def test_expired_spool_terminal_even_if_authority_is_revoked(config):
    first, repo, _, _, _, ingestion = worker(config)
    target = first.manifest.targets[0]
    ingestion.ingest.side_effect = ConnectionError()
    await first.collect_target(target)
    repo.batches[target.device_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    second, _, _, auth, transport, replay = worker(config, repository=repo, authority=AsyncMock(side_effect=SNMPError("revoked")))
    assert await second.collect_target(target) == "expired"
    auth.assert_not_awaited()
    transport.get.assert_not_awaited()
    replay.ingest.assert_not_awaited()


async def test_revoked_before_read_and_between_publications(config):
    instance, repo, _, auth, transport, ingestion = worker(config)
    target = instance.manifest.targets[0]
    auth.side_effect = SNMPError("revoked")
    assert await instance.collect_target(target) == "collection_deferred"
    transport.get.assert_not_awaited()
    auth.side_effect = None

    async def revoke(**_):
        auth.side_effect = SNMPError("revoked")

    ingestion.ingest.side_effect = revoke
    assert await instance.collect_target(target) == "collection_deferred"
    assert ingestion.ingest.await_count == 1
    assert repo.batches[target.device_id].cursor == 1
    restarted, _, _, _, _, replay = worker(config, repository=repo, authority=auth)
    assert await restarted.collect_target(target) == "collection_deferred"
    replay.ingest.assert_not_awaited()


async def test_bad_target_does_not_block_healthy_and_bounds_concurrency(config):
    instance, _, _, _, transport, ingestion = worker(config)
    active = maximum = 0

    async def get(binding, _):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0.01)
            if binding.device_id.int == 1:
                raise SNMPError("snmp_timeout")
            return InterfaceCounters(1000, 1, 1, 2, 1000000000, 0, ".1.2.3")
        finally:
            active -= 1

    transport.get.side_effect = get
    assert await instance.run_once() == ["collection_deferred", "published"]
    assert maximum <= config.concurrency
    assert all(call.kwargs["raw"]["device_id"] == str(uuid.UUID(int=2)) for call in ingestion.ingest.call_args_list)


async def test_manifest_revocation_during_read_prevents_spool_or_publish(config):
    instance, repo, _, _, transport, ingestion = worker(config)
    original = transport.get.return_value

    async def revoke(*_):
        config.manifest_path.unlink()
        return original

    transport.get.side_effect = revoke
    assert await instance.collect_target(instance.manifest.targets[0]) == "collection_deferred"
    assert not repo.batches
    ingestion.ingest.assert_not_awaited()


async def test_watchdog_loss_cancels_io_before_releasing_lock(config):
    config = config.model_copy(update={"lease_seconds": 0.03})
    instance, _, locks, _, transport, ingestion = worker(config)
    cancelled = asyncio.Event()

    async def get(*_):
        try:
            await asyncio.Event().wait()
        finally:
            assert locks.held
            cancelled.set()

    async def check(*, renew=False):
        if renew:
            raise SNMPError("fleet_lease_lost")

    locks.check.side_effect = check
    transport.get.side_effect = get
    assert await instance.collect_target(instance.manifest.targets[0]) == "collection_deferred"
    assert cancelled.is_set() and not locks.held
    ingestion.ingest.assert_not_awaited()


async def test_health_does_not_present_old_publication_as_fresh(config):
    instance, repo, _, _, _, _ = worker(config)
    repo.health = AsyncMock(return_value=[{
        "device_id": str(target.device_id), "outcome": "published",
        "last_published_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    } for target in instance.manifest.targets])
    health = await instance.health()
    assert health["status"] == "degraded"
    assert all(not row["fresh"] for row in health["devices"])
    assert instance.redis.set.call_args.kwargs["ex"] == config.health_ttl_seconds
