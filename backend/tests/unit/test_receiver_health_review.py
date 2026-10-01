"""ADR023Review9–11 + ADR-028 C21 receiver-health regressions, synthetic installation seam only."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.modules.autonomy.execution_client import JournalExecutionClient, installed_execution_clients
from app.modules.autonomy.execution_settings import (
    CONFIG_HASH,
    CONFIG_PATH,
    ExecutionClientConfig,
    clear_verified_installations,
)
from app.modules.autonomy.health_secret import (
    LEGACY_HMAC_ENV,
    PRIVATE_KEY_ENV,
    PUBLIC_KEY_ENV,
    ReceiptSigner,
    ReceiptVerifier,
    key_id_for,
    load_signing_key,
    load_verify_key,
    receipt_credentials,
    signing_credentials,
)
from app.modules.autonomy.receiver_health import RECEIPT_V1, RECEIPT_V2, ReceiverHealth
from tests.autonomous_execution_support import fixture


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    for name in (PRIVATE_KEY_ENV, PUBLIC_KEY_ENV, LEGACY_HMAC_ENV):
        monkeypatch.delenv(name, raising=False)
    clear_verified_installations()
    yield
    clear_verified_installations()


def pair():
    key = Ed25519PrivateKey.generate()
    return ReceiptSigner(key), ReceiptVerifier(key.public_key())


def write_keys(directory, *, private_mode=0o600, public_mode=0o400, key=None):
    key = key or Ed25519PrivateKey.generate()
    private, public = directory / "receiver-health.key", directory / "receiver-health.pub"
    for path in (private, public):
        path.unlink(missing_ok=True)
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                     serialization.PublicFormat.SubjectPublicKeyInfo))
    private.chmod(private_mode)
    public.chmod(public_mode)
    return key, private, public


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
def test_legacy_key_loader_requires_private0600(tmp_path, monkeypatch, mode):
    monkeypatch.setenv(LEGACY_HMAC_ENV, "true")
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


def test_symmetric_secret_is_never_read_without_legacy_toggle(tmp_path, monkeypatch):
    """C21: an ordinary verifier no longer holds the shared secret (it could forge receipts)."""
    case, key = fixture(), os.urandom(32)
    tmp_path.chmod(0o755)
    monkeypatch.setattr("app.modules.autonomy.safety_installation.load_independently_validated_safety", lambda **_: case.installation)
    read = MagicMock(side_effect=AssertionError("secret must not be read"))
    monkeypatch.setattr("app.modules.autonomy.execution_settings.read_health_secret", read)
    assert config_for(tmp_path, case, key).load() == (case.installation, None)
    config = config_for(tmp_path, case, key).model_copy(update={"health_key": None})
    assert "health_key" not in config.model_dump(mode="json")


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


@pytest.mark.parametrize("modes,valid", [((0o600, 0o400), True), ((0o400, 0o600), True), ((0o644, 0o400), False),
                                         ((0o600, 0o644), False), ((0o640, 0o400), False)])
def test_ed25519_key_files_require_0400_or_0600(tmp_path, modes, valid):
    root = tmp_path / "keys"
    root.mkdir(mode=0o700)
    key, private, public = write_keys(root, private_mode=modes[0], public_mode=modes[1])
    if valid:
        signer, verifier = load_signing_key(private), load_verify_key(public)
        assert signer.key_id == verifier.key_id == key_id_for(key.public_key())
        assert len(signer.key_id) == 16 and signer.key_id == hashlib.sha256(key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).hexdigest()[:16]
    else:
        with pytest.raises(ValueError, match="0400_or_0600"):
            load_signing_key(private) if modes[0] not in (0o400, 0o600) else load_verify_key(public)


@pytest.mark.parametrize("change", ["symlink", "writable_ancestor", "relative", "not_ed25519", "garbage"])
def test_ed25519_key_file_rejects_unsafe_or_foreign_material(tmp_path, change):
    root = tmp_path / "keys"
    root.mkdir(mode=0o700)
    _, private, public = write_keys(root)
    target = public
    if change == "symlink":
        (root / "link.pub").symlink_to(public)
        target = root / "link.pub"
    elif change == "writable_ancestor":
        root.chmod(0o777)
    elif change == "relative":
        target = Path("keys/receiver-health.pub")
    elif change == "not_ed25519":
        other = X25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        public.chmod(0o600)
        public.write_bytes(other)
    else:
        public.chmod(0o600)
        public.write_bytes(b"-----BEGIN PUBLIC KEY-----\nnot-a-key\n-----END PUBLIC KEY-----\n")
    with pytest.raises(ValueError):
        load_verify_key(target)
    if change == "writable_ancestor":
        with pytest.raises(ValueError):
            load_signing_key(private)


class MemoryRedis:
    def __init__(self):
        self.raw, self.lifetime = None, 10

    async def set(self, key, value, ex):
        self.raw, self.lifetime = value, ex

    async def get(self, key):
        return self.raw

    async def ttl(self, key):
        return self.lifetime


def publisher_and_verifier(redis, installation, *, max_age_seconds=10):
    signer, verifier = pair()
    return (ReceiverHealth(redis, installation, "unit-lab", signer=signer, max_age_seconds=max_age_seconds),
            ReceiverHealth(redis, installation, "unit-lab", verifier=verifier, max_age_seconds=max_age_seconds))


async def test_signed_receipt_roundtrip_carries_key_id():
    redis, case = MemoryRedis(), fixture()
    publisher, verifier = publisher_and_verifier(redis, case.installation)
    await publisher.completed()
    body = await verifier.check()
    receipt = json.loads(redis.raw)
    assert set(receipt) == {"body", "signature"} and body["version"] == RECEIPT_V2
    assert body["key_id"] == verifier.verifier.key_id == publisher.signer.key_id
    with pytest.raises(ValueError, match="signing_key_unconfigured"):
        await verifier.completed()  # the public-key holder cannot mint receipts


@pytest.mark.parametrize("attack", ["other_key", "same_key_id_other_key", "body_tamper", "signature_tamper",
                                    "hmac_forgery", "unsigned"])
async def test_verifier_rejects_forged_receipts(attack):
    redis, case = MemoryRedis(), fixture()
    publisher, verifier = publisher_and_verifier(redis, case.installation)
    await publisher.completed()
    receipt = json.loads(redis.raw)
    body = receipt["body"]
    if attack == "other_key":
        forger, _ = pair()
        body["key_id"] = forger.key_id
        receipt["signature"] = forger.sign(ReceiverHealth.canonical(body))
        match = "key_id_mismatch"
    elif attack == "same_key_id_other_key":
        forger, _ = pair()
        receipt["signature"] = forger.sign(ReceiverHealth.canonical(body))
        match = "signature_invalid"
    elif attack == "body_tamper":
        body["iteration"] += 1
        match = "signature_invalid"
    elif attack == "signature_tamper":
        receipt["signature"] = ("0" if receipt["signature"][0] != "0" else "1") + receipt["signature"][1:]
        match = "signature_invalid"
    elif attack == "hmac_forgery":
        # Anyone who knows a shared secret could mint this; rejected unless legacy mode is on.
        legacy = dict(body, version=RECEIPT_V1)
        legacy.pop("key_id")
        receipt = {"body": legacy, "mac": hmac.new(b"k" * 32, ReceiverHealth.canonical(legacy), hashlib.sha256).hexdigest()}
        match = "legacy_hmac_disabled"
    else:
        receipt = {"body": body}
        match = "invalid"
    redis.raw = ReceiverHealth.canonical(receipt)
    with pytest.raises(ValueError, match=match):
        await verifier.check()


async def test_legacy_hmac_receipts_only_with_toggle(monkeypatch):
    redis, case, key = MemoryRedis(), fixture(), b"a" * 32
    legacy = ReceiverHealth(redis, case.installation, "unit-lab", key)
    with pytest.raises(ValueError, match="signing_key_unconfigured"):
        await legacy.completed()
    monkeypatch.setenv(LEGACY_HMAC_ENV, "true")
    await legacy.completed()
    assert json.loads(redis.raw)["body"]["version"] == RECEIPT_V1
    assert (await legacy.check())["iteration"] == 1
    monkeypatch.setenv(LEGACY_HMAC_ENV, "false")
    with pytest.raises(ValueError, match="legacy_hmac_disabled"):
        await legacy.check()
    _, verifier = pair()
    monkeypatch.setenv(LEGACY_HMAC_ENV, "true")
    signed_only = ReceiverHealth(redis, case.installation, "unit-lab", verifier=verifier)
    with pytest.raises(ValueError, match="legacy_hmac_disabled"):
        await signed_only.check()  # a verifier without the legacy secret never accepts HMAC


def test_credential_loaders_are_role_separated(tmp_path, monkeypatch):
    root = tmp_path / "keys"
    root.mkdir(mode=0o700)
    _, private, public = write_keys(root)
    with pytest.raises(ValueError, match="verifier_unconfigured"):
        receipt_credentials(b"a" * 32)
    with pytest.raises(ValueError, match="signing_key_unconfigured"):
        signing_credentials(b"a" * 32)
    monkeypatch.setenv(PUBLIC_KEY_ENV, str(public))
    monkeypatch.setenv(PRIVATE_KEY_ENV, str(private))
    verifier, legacy = receipt_credentials(b"a" * 32)
    signer, signer_legacy = signing_credentials(b"a" * 32)
    assert isinstance(verifier, ReceiptVerifier) and not hasattr(verifier, "sign")
    assert verifier.key_id == signer.key_id and legacy is None and signer_legacy is None
    monkeypatch.setenv(LEGACY_HMAC_ENV, "true")
    assert receipt_credentials(b"a" * 32)[1] == b"a" * 32


async def test_expiry_during_renewed_ttl_rejects_old_authenticated_body(monkeypatch):
    clock, redis = [1000.], MemoryRedis()
    monkeypatch.setattr("app.modules.autonomy.receiver_health.time.time", lambda: clock[0])
    publisher, health = publisher_and_verifier(redis, fixture().installation)
    await publisher.completed()
    async def ttl(key):
        clock[0] = 1011.
        await publisher.completed()
        return 10
    redis.ttl = ttl
    with pytest.raises(ValueError, match="stale"):
        await health.check()


async def test_health_roundtrip_is_bounded_and_cancels_waiting_transport():
    import asyncio
    redis = MemoryRedis()
    publisher, health = publisher_and_verifier(redis, fixture().installation)
    await publisher.completed()
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
    publisher, health = publisher_and_verifier(redis, case.installation)
    await publisher.completed()
    async def stage(*_):
        # Staging waits on DB locks long enough for the verified receipt to expire.
        clock[0] += 11
        await publisher.completed()
    authority = AsyncMock()
    monkeypatch.setattr("app.modules.autonomy.execution_authority.ExecutionAuthority.check", authority)
    monkeypatch.setattr("app.modules.autonomy.execution_repository.ExecutionRepository.stage", stage)
    db = SimpleNamespace(commit=AsyncMock())
    client = JournalExecutionClient(None, redis, case.installation, "unit-lab", health)
    assert (await client.refresh_status()).status == "ready"  # readiness runs before the control lock
    with pytest.raises(ValueError, match="not_ready_after_staging"):
        await client.accept(db, case.auth)
    db.commit.assert_not_called()
    authority.assert_awaited_once()


async def test_accept_performs_no_provider_io_under_the_control_lock(monkeypatch):
    """ADR-028 fix 1: no reload, verification or Redis round trip inside acceptance."""
    case, redis = fixture(), MemoryRedis()
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation"))
    publisher, health = publisher_and_verifier(redis, case.installation)
    await publisher.completed()
    reload = AsyncMock()
    client = JournalExecutionClient(None, redis, case.installation, "unit-lab", health,
                                    reload_installation=lambda: (case.installation, health.credentials_identity, None))
    assert (await client.refresh_status()).status == "ready"
    health.check = AsyncMock(side_effect=AssertionError("no receipt read under the lock"))
    client.reload_installation = reload
    monkeypatch.setattr("app.modules.autonomy.execution_authority.ExecutionAuthority.check", AsyncMock())
    monkeypatch.setattr("app.modules.autonomy.execution_repository.ExecutionRepository.stage", AsyncMock())
    await client.accept(SimpleNamespace(), case.auth)
    reload.assert_not_called()
    health.check.assert_not_awaited()


async def test_accept_refuses_without_prior_fresh_refresh(monkeypatch):
    case, redis = fixture(), MemoryRedis()
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation"))
    _, health = publisher_and_verifier(redis, case.installation)
    client = JournalExecutionClient(None, redis, case.installation, "unit-lab", health)
    with pytest.raises(ValueError, match="autonomous_receiver_not_ready"):
        await client.accept(SimpleNamespace(), case.auth)


@pytest.mark.parametrize("change", ["health_max_age_seconds", "resource_id", "evidence_root", "source_root", "health_key",
                                    "config_path", "config_pin", "public_key"])
async def test_factory_rejects_entire_config_change(tmp_path, monkeypatch, change):
    case, key, redis = fixture(), os.urandom(32), MemoryRedis()
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    signing_key, _, public = write_keys(keys)
    monkeypatch.setenv(PUBLIC_KEY_ENV, str(public))
    config = config_for(tmp_path, case, key).model_copy(update={"health_max_age_seconds": 30})
    current = [config]
    monkeypatch.setenv(CONFIG_PATH, str(tmp_path / "config.json"))
    monkeypatch.setenv(CONFIG_HASH, "f" * 64)
    monkeypatch.setattr("app.modules.autonomy.execution_settings.load_config", lambda: current[0])
    monkeypatch.setattr(ExecutionClientConfig, "load", lambda _: (case.installation, None))
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation"))
    _, client, _ = installed_execution_clients(None, redis)
    publisher = ReceiverHealth(redis, case.installation, "unit-lab", signer=ReceiptSigner(signing_key),
                               max_age_seconds=30)
    await publisher.completed()
    assert (await client.refresh_status()).status == "ready"
    if change == "config_path":
        monkeypatch.setenv(CONFIG_PATH, str(tmp_path / "other.json"))
    elif change == "config_pin":
        monkeypatch.setenv(CONFIG_HASH, "a" * 64)
    elif change == "public_key":
        write_keys(keys)  # key rotation needs an explicit restart, never a silent swap
    else:
        value = 1 if change == "health_max_age_seconds" else "changed"
        if change == "health_key":
            value = config.health_key.model_copy(update={"path": "another.key"})
        current[0] = config.model_copy(update={change: value})
    assert (await client.refresh_status()).status == "unavailable"


def test_factory_without_any_receipt_verifier_is_blocked(tmp_path, monkeypatch):
    case, key = fixture(), os.urandom(32)
    monkeypatch.setenv(CONFIG_PATH, str(tmp_path / "config.json"))
    monkeypatch.setenv(CONFIG_HASH, "f" * 64)
    monkeypatch.setattr("app.modules.autonomy.execution_settings.load_config", lambda: config_for(tmp_path, case, key))
    monkeypatch.setattr(ExecutionClientConfig, "load", lambda _: (case.installation, None))
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation"))
    safety, client, recovery = installed_execution_clients(None, MemoryRedis())
    assert client.status.status == "unavailable" and getattr(client, "blocked", False) is True
    assert safety is client is recovery


def test_verified_installation_is_cached_per_config_digest(tmp_path, monkeypatch):
    from app.modules.autonomy import execution_settings

    case, key = fixture(), os.urandom(32)
    calls = []
    monkeypatch.setattr(ExecutionClientConfig, "load", lambda self: calls.append(1) or (case.installation, None))
    config = config_for(tmp_path, case, key)
    now = [100.]
    clock = lambda: now[0]  # noqa: E731
    assert execution_settings.verified_installation(config, clock=clock)[0] is case.installation
    assert execution_settings.verified_installation(config, clock=clock)[0] is case.installation
    assert len(calls) == 1
    now[0] += execution_settings.REVERIFY_SECONDS + 1
    execution_settings.verified_installation(config, clock=clock)
    assert len(calls) == 2
    other = config.model_copy(update={"resource_id": "other-lab"})
    execution_settings.verified_installation(other, clock=clock)
    assert len(calls) == 3


@pytest.mark.parametrize("module", ["execution_client", "execution_settings", "providers", "frr_contract", "health_secret"])
def test_journal_import_subprocess_has_no_privileged_driver_modules(module):
    root = Path(__file__).parents[3]
    code = f"import app.modules.autonomy.{module},sys; print(','.join(sorted(k for k in sys.modules if k.startswith('emulation.'))))"
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True,
        cwd=root, env={**os.environ, "PYTHONPATH": str(root / "backend") + os.pathsep + str(root), "PYTHONDONTWRITEBYTECODE": "1"})
    assert not {"emulation.autonomous_frr", "emulation.autonomous_namespace", "emulation.autonomous_driver",
                "emulation.ospf", "emulation.actions", "emulation.runner"} & set(result.stdout.strip().split(","))


def test_monotonic_and_wall_receipt_lifetime_both_bound_readiness(monkeypatch):
    case = fixture()
    _, health = publisher_and_verifier(MemoryRedis(), case.installation)
    client = JournalExecutionClient(None, None, case.installation, "unit-lab", health)
    client._ready_until, client._receipt_valid_until = time.monotonic() + 5, time.time() + 5
    assert client.status.status == "ready"
    client._receipt_valid_until = time.time() - 1
    assert client.status.status == "unavailable"
