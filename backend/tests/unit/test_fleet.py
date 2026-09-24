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


# ---------------------------------------------------------------- ADR-028 scheduler / diagnostics


def many_targets_config(tmp_path, count, *, concurrency=4, interval=10.0):
    targets = [{"device_id": str(uuid.UUID(int=1000 + number)),
                "binding_path": str(tmp_path / f"binding{number}.json"),
                "credentials_path": str(tmp_path / f"secret{number}.json"),
                "interval_seconds": interval, "backoff_max_seconds": interval * 8}
               for number in range(count)]
    manifest = protected(tmp_path / "manifest.json", {"version": 1, "targets": targets})
    return FleetSettings(manifest_path=manifest, concurrency=concurrency, scan_seconds=1.0)


class VirtualTime:
    """Deterministic event-loop driver: collections finish instantly; time only
    advances when every slot is idle and the scheduler asked to sleep."""

    def __init__(self, instance, until):
        self.now, self.until, self.instance = 0.0, until, instance
        self.stop = asyncio.Event()

    def clock(self):
        return self.now

    async def pause(self, stop, timeout):
        for _ in range(3):
            await asyncio.sleep(0)
        if any(task.done() for task in self.instance._active.values()):
            return  # a slot freed: the real scheduler wakes immediately
        self.now += max(timeout, 1e-6)
        if self.now >= self.until:
            self.stop.set()


async def run_virtual(instance, until):
    driver = VirtualTime(instance, until)
    instance._clock, instance._pause = driver.clock, driver.pause
    starts = {}

    async def collect(target):
        starts.setdefault(target.device_id, []).append(driver.now)
        return "published"

    instance.collect_target = collect
    instance.repository.health = AsyncMock(return_value=[])
    await instance.run(driver.stop)
    return starts


async def test_run_polls_256_targets_at_their_configured_interval(tmp_path):
    """Regression: rotation advanced by one per scan, so the effective interval was
    ~targets x scan seconds (256 s) instead of the configured 10 s."""
    config = many_targets_config(tmp_path, 256, concurrency=4, interval=10.0)
    instance, *_ = worker(config)
    starts = await run_virtual(instance, until=100.0)
    assert len(starts) == 256
    gaps = [later - earlier for times in starts.values() for earlier, later in zip(times, times[1:])]
    assert all(len(times) >= 9 for times in starts.values())
    assert gaps and max(gaps) <= 10.0 + 1e-6 * 10 and min(gaps) >= 10.0 - 1e-6
    assert instance.schedule_summary(100.0)["active"] == 0


async def test_free_slots_go_to_the_most_overdue_targets(tmp_path):
    config = many_targets_config(tmp_path, 5, concurrency=2)
    instance, *_ = worker(config)
    ids = [target.device_id for target in instance.manifest.targets]
    instance._next_due = {ids[0]: 50.0, ids[1]: 10.0, ids[2]: 5.0, ids[3]: 99.0, ids[4]: 120.0}
    assert [t.device_id for t in instance.due_targets(100.0)] == [ids[2], ids[1]]
    instance._active[ids[2]] = asyncio.get_running_loop().create_future()
    assert [t.device_id for t in instance.due_targets(100.0)] == [ids[1]]
    assert instance.schedule_summary(100.0) == {"active": 1, "due": 3, "max_overdue_seconds": 90.0}
    instance._active[ids[2]].cancel()


def test_failures_back_off_exponentially_and_success_resets(tmp_path):
    config = many_targets_config(tmp_path, 1, interval=2.0)
    instance, *_ = worker(config)
    target = instance.manifest.targets[0]
    delays = [instance._delay(target, "collection_deferred") for _ in range(5)]
    assert delays == [4.0, 8.0, 16.0, 16.0, 16.0]  # capped at backoff_max_seconds
    assert instance._delay(target, "not_due_or_owned") == 2.0
    assert instance._delay(target, "collection_deferred") == 16.0  # owner/lease skip keeps backoff
    assert instance._delay(target, "published") == 2.0
    assert instance._delay(target, "lease_or_storage_unavailable") == 4.0


async def test_collection_failures_log_fixed_codes_and_are_counted(config, monkeypatch):
    from app.modules.telemetry import fleet as fleet_module

    logged = []
    monkeypatch.setattr(fleet_module.logger, "warning", lambda event, **fields: logged.append((event, fields)))
    instance, _, locks, _, transport, _ = worker(config)
    transport.get.side_effect = RuntimeError("postgresql://user:hunter2@db/nanfo")
    assert await instance.collect_target(instance.manifest.targets[0]) == "collection_deferred"
    event, fields = logged[-1]
    assert event == "fleet_collection_deferred"
    assert fields["error_code"] == "fleet_collection_failed" and fields["error_type"] == "RuntimeError"
    assert "hunter2" not in repr(logged)
    transport.get.side_effect = SNMPError("snmp_timeout")
    await instance.collect_target(instance.manifest.targets[0])
    assert logged[-1][1]["error_code"] == "snmp_timeout"

    @asynccontextmanager
    async def broken(*_):
        raise ConnectionError("redis://:hunter2@cache")
        yield  # pragma: no cover

    locks.acquire = broken
    assert await instance.collect_target(instance.manifest.targets[0]) == "lease_or_storage_unavailable"
    assert logged[-1][0] == "fleet_lease_or_storage_unavailable" and "hunter2" not in repr(logged)
    assert instance.failures.snapshot() == {
        "fleet_collection_failed": 1, "fleet_lease_or_storage_unavailable": 1, "snmp_timeout": 1}
    instance.repository.health = AsyncMock(return_value=[])
    assert (await instance.health())["errors"] == instance.failures.snapshot()


async def test_health_publication_failure_is_counted_and_slo_hosted(config):
    instance, repo, *_ = worker(config)
    repo.health = AsyncMock(side_effect=ConnectionError("down"))
    instance.slo_evaluator = SimpleNamespace(maybe_evaluate=AsyncMock(side_effect=RuntimeError("redis down")))
    await instance._housekeeping(0.0)
    assert instance.failures.snapshot() == {"fleet_health_unavailable": 1, "fleet_slo_unavailable": 1}
    instance.slo_evaluator.maybe_evaluate.assert_awaited_once()
    assert instance._next_housekeeping == config.scan_seconds


async def test_fleet_batch_performs_one_full_owner_check(config, monkeypatch):
    from app.modules.telemetry import snmp_ownership

    full = AsyncMock()
    monkeypatch.setattr(snmp_ownership, "validate_owner_scope", full)
    exists = AsyncMock(return_value=True)
    monkeypatch.setattr(snmp_ownership.IdentityDirectoryService, "user_exists", exists)

    @asynccontextmanager
    async def session():
        yield object()

    boundaries = []

    def boundary_factory(**kwargs):
        boundaries.append(snmp_ownership.SNMPOwnerBoundary(**{**kwargs, "session_factory": session}))
        return boundaries[-1]

    instance, *_ = worker(config)
    instance.boundary_factory = boundary_factory
    assert await instance.collect_target(instance.manifest.targets[0]) == "published"
    assert full.await_count == 1 and boundaries[0].full_checks == 1
    # Read checks around the single GET plus one write check per published sample.
    assert exists.await_count >= 3
    assert await instance.collect_target(instance.manifest.targets[0]) == "published"
    assert full.await_count == 2  # every batch starts with a fresh full authorization
