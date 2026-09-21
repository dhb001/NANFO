"""ADR023Review9–11 safe regressions, synthetic installation seam only."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.autonomy.execution_client import JournalExecutionClient, installed_execution_clients
from app.modules.autonomy.execution_settings import CONFIG_HASH, CONFIG_PATH, ExecutionClientConfig
from app.modules.autonomy.receiver_health import ReceiverHealth
from tests.autonomous_execution_support import fixture


def config_for(root, case, key):
    data = case.installation.data
    return ExecutionClientConfig(version="nanfo.autonomous-provider-installation/v1", execution_mode="emulation",
        evidence_root=str(root), source_root=str(root), calibration_path="calibration.json",
        calibration_sha256="a" * 64, provider_path="provider.json", provider_sha256=case.installation.sha256,
        expected_scope=dict(network_id=str(data.network_id), run_id=data.calibration.run_id,
            provider_id=data.calibration.provider_id, environment="isolated-emulation",
            configuration_sha256=data.configuration_sha256, egress_ids=data.calibration.egress_ids,
            demand_ids=data.calibration.demand_ids, action_ids=[a.action_id for a in data.actions],
            max_dt_seconds=1., max_delay_seconds=.9), trusted_preregistrations={}, trusted_attesters=set(),
        accepted_guarantee_sha256=set(), accepted_runtime_sha256=set(), accepted_equivalence_sha256=set(),
        resource_id="unit-lab", health_key=dict(path="health.key", sha256=hashlib.sha256(key).hexdigest(), size_bytes=len(key)))


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o660, 0o400, 0o600])
def test_actual_key_loader_requires_private0600(tmp_path, monkeypatch, mode):
    case, key = fixture(), os.urandom(32)
    tmp_path.chmod(0o755)
    path = tmp_path / "health.key"
    path.write_bytes(key)
    path.chmod(mode)
    monkeypatch.setattr("app.modules.autonomy.safety_installation.load_independently_validated_safety", lambda **_: case.installation)
    if mode == 0o600:
        assert config_for(tmp_path, case, key).load()[1] == key
    else:
        with pytest.raises(ValueError, match="private_0600"):
            config_for(tmp_path, case, key).load()


@pytest.mark.parametrize("change", ["symlink", "ancestor_symlink", "writable_ancestor", "foreign_owner", "chmod_during_read", "hardlink"])
def test_secret_descriptor_and_ancestry_checks(tmp_path, monkeypatch, change):
    from app.modules.autonomy.health_secret import read_health_secret
    case, key = fixture(), os.urandom(32)
    root = tmp_path / "keys"
    root.mkdir(mode=0o700)
    path = root / "health.key"
    path.write_bytes(key)
    path.chmod(0o600)
    config = config_for(root, case, key)
    if change == "symlink":
        path.rename(root / "actual")
        path.symlink_to(root / "actual")
    elif change == "ancestor_symlink":
        root.rename(tmp_path / "actual")
        root.symlink_to(tmp_path / "actual", target_is_directory=True)
    elif change == "writable_ancestor":
        root.chmod(0o777)
    elif change == "foreign_owner":
        original = os.fstat
        def fstat(fd):
            info = original(fd)
            if info.st_ino == path.stat().st_ino:
                return SimpleNamespace(**{k: getattr(info, k) for k in dir(info) if k.startswith("st_") and k != "st_uid"},
                                       st_uid=12345678)
            return info
        monkeypatch.setattr("app.modules.autonomy.health_secret.os.fstat", fstat)
    elif change == "hardlink":
        os.link(path, root / "second")
    else:
        original = os.fdopen
        def fdopen(fd, *args, **kwargs):
            path.chmod(0o644)
            return original(fd, *args, **kwargs)
        monkeypatch.setattr("app.modules.autonomy.health_secret.os.fdopen", fdopen)
    with pytest.raises(ValueError):
        read_health_secret(root, config.health_key)


class MemoryRedis:
    def __init__(self):
        self.raw, self.lifetime = None, 10

    async def set(self, key, value, ex):
        self.raw, self.lifetime = value, ex

    async def get(self, key):
        return self.raw

    async def ttl(self, key):
        return self.lifetime


async def test_expiry_during_renewed_ttl_rejects_old_authenticated_body(monkeypatch):
    clock, redis = [1000.], MemoryRedis()
    monkeypatch.setattr("app.modules.autonomy.receiver_health.time.time", lambda: clock[0])
    health = ReceiverHealth(redis, fixture().installation, "unit-lab", b"a" * 32)
    await health.completed()
    async def ttl(key):
        clock[0] = 1011.
        await health.completed()
        return 10
    redis.ttl = ttl
    with pytest.raises(ValueError, match="stale"):
        await health.check()


async def test_health_roundtrip_is_bounded_and_cancels_waiting_transport():
    import asyncio
    redis = MemoryRedis()
    health = ReceiverHealth(redis, fixture().installation, "unit-lab", b"a" * 32)
    await health.completed()
    cancelled = asyncio.Event()
    async def ttl(key):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    redis.ttl = ttl
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(health.check(), 3)
    assert cancelled.is_set()


async def test_acceptance_post_stage_receipt_expires_during_roundtrip(monkeypatch):
    case, redis, clock = fixture(), MemoryRedis(), [1000.]
    monkeypatch.setattr("app.modules.autonomy.receiver_health.time.time", lambda: clock[0])
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation"))
    health = ReceiverHealth(redis, case.installation, "unit-lab", b"a" * 32)
    await health.completed()
    async def stage(*_):
        async def ttl(key):
            clock[0] += 11
            await health.completed()
            return 10
        redis.ttl = ttl
    authority = AsyncMock()
    monkeypatch.setattr("app.modules.autonomy.execution_authority.ExecutionAuthority.check", authority)
    monkeypatch.setattr("app.modules.autonomy.execution_repository.ExecutionRepository.stage", stage)
    db = SimpleNamespace(commit=AsyncMock())
    client = JournalExecutionClient(None, redis, case.installation, "unit-lab", health)
    with pytest.raises(ValueError, match="not_ready_after_staging"):
        await client.accept(db, case.auth)
    db.commit.assert_not_called()
    authority.assert_awaited_once()


@pytest.mark.parametrize("change", ["health_max_age_seconds", "resource_id", "evidence_root", "source_root", "health_key", "config_path", "config_pin"])
async def test_factory_rejects_entire_config_change(tmp_path, monkeypatch, change):
    case, key, redis = fixture(), os.urandom(32), MemoryRedis()
    config = config_for(tmp_path, case, key).model_copy(update={"health_max_age_seconds": 30})
    current = [config]
    monkeypatch.setenv(CONFIG_PATH, str(tmp_path / "config.json"))
    monkeypatch.setenv(CONFIG_HASH, "f" * 64)
    monkeypatch.setattr("app.modules.autonomy.execution_settings.load_config", lambda: current[0])
    monkeypatch.setattr(ExecutionClientConfig, "load", lambda _: (case.installation, key))
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation"))
    _, client, _ = installed_execution_clients(None, redis)
    await client.health.completed()
    assert (await client.refresh_status()).status == "ready"
    if change == "config_path":
        monkeypatch.setenv(CONFIG_PATH, str(tmp_path / "other.json"))
    elif change == "config_pin":
        monkeypatch.setenv(CONFIG_HASH, "a" * 64)
    else:
        value = 1 if change == "health_max_age_seconds" else "changed"
        if change == "health_key":
            value = config.health_key.model_copy(update={"path": "another.key"})
        current[0] = config.model_copy(update={change: value})
    assert (await client.refresh_status()).status == "unavailable"


@pytest.mark.parametrize("module", ["execution_client", "execution_settings", "providers", "frr_contract"])
def test_journal_import_subprocess_has_no_privileged_driver_modules(module):
    root = Path(__file__).parents[3]
    code = f"import app.modules.autonomy.{module},sys; print(','.join(sorted(k for k in sys.modules if k.startswith('emulation.'))))"
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True,
        cwd=root, env={**os.environ, "PYTHONPATH": str(root / "backend") + os.pathsep + str(root), "PYTHONDONTWRITEBYTECODE": "1"})
    assert not {"emulation.autonomous_frr", "emulation.autonomous_namespace", "emulation.autonomous_driver",
                "emulation.ospf", "emulation.actions", "emulation.runner"} & set(result.stdout.strip().split(","))
