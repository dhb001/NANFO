"""Default/invalid composition and authenticated receiver-progress readiness."""

import hashlib
import json
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.modules.autonomy.execution_client import JournalExecutionClient
from app.modules.autonomy.execution_settings import CONFIG_HASH, CONFIG_PATH, ExecutionClientConfig, load_config
from app.modules.autonomy.health_secret import ReceiptSigner, ReceiptVerifier
from app.modules.autonomy.providers import UnavailableExecutor, UnavailableRecovery, installed_providers
from app.modules.autonomy.receiver_health import ReceiverHealth
from tests.autonomous_execution_support import fixture


def signed_pair(redis, installation):
    key = Ed25519PrivateKey.generate()
    return (ReceiverHealth(redis, installation, "unit-lab", signer=ReceiptSigner(key)),
            ReceiverHealth(redis, installation, "unit-lab", verifier=ReceiptVerifier(key.public_key())))


@pytest.mark.parametrize("mode,config", [("emulation", None), ("emulation", "partial"), ("production", "partial")])
def test_factory_default_partial_and_production_never_start_receiver(monkeypatch, mode, config):
    monkeypatch.delenv(CONFIG_PATH, raising=False)
    monkeypatch.delenv(CONFIG_HASH, raising=False)
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(EXECUTION_MODE=mode))
    if config:
        monkeypatch.setenv(CONFIG_PATH, "/nonexistent/protected.json")
    providers = installed_providers(None, None)
    # ADR-028 fix 2: no Intent-module cancellation provider exists any more.
    assert not hasattr(providers, "cancellation")
    assert not hasattr(providers.executor, "run") and not hasattr(providers.executor, "driver")
    assert providers.executor.status.status == "unavailable"
    if config is None:
        assert isinstance(providers.executor, UnavailableExecutor)
        assert isinstance(providers.recovery, UnavailableRecovery)


def test_protected_config_requires_exact_digest(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{}')
    with pytest.raises(ValueError):
        load_config(str(path), "0" * 64)
    with pytest.raises(ValueError):
        load_config(str(path), hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError):
        ExecutionClientConfig.model_validate({"execution_mode": "production"})


async def test_progress_auth_scope_ttl_and_freshness(fake_redis):
    case = fixture()
    publisher, health = signed_pair(fake_redis, case.installation)
    client = JournalExecutionClient(None, fake_redis, case.installation, "unit-lab", health)
    assert (await client.refresh_status()).status == "unavailable"
    await publisher.completed()
    assert (await client.refresh_status()).status == "ready"
    _, other = signed_pair(fake_redis, case.installation)
    with pytest.raises(ValueError, match="key_id_mismatch"):
        await other.check()
    raw = json.loads(await fake_redis.get(health.redis_key))
    raw["body"]["completed_at"] = time.time() - 20
    raw["signature"] = publisher.signer.sign(publisher.canonical(raw["body"]))
    await fake_redis.set(health.redis_key, health.canonical(raw), ex=10)
    assert (await client.refresh_status()).status == "unavailable"
    await publisher.completed()
    await fake_redis.persist(health.redis_key)
    assert (await client.refresh_status()).status == "unavailable"
    assert not hasattr(client, "run") and not hasattr(client, "driver")


async def test_receipt_foreign_scope_and_publisher_signature_tamper_fail(fake_redis):
    case = fixture()
    publisher, health = signed_pair(fake_redis, case.installation)
    await publisher.completed()
    receipt = json.loads(await fake_redis.get(health.redis_key))
    receipt["body"]["resource_id"] = "other-lab"
    # Even a valid signature for a different receiver scope cannot qualify this client.
    receipt["signature"] = publisher.signer.sign(publisher.canonical(receipt["body"]))
    await fake_redis.set(health.redis_key, health.canonical(receipt), ex=10)
    with pytest.raises(ValueError):
        await health.check()
    await publisher.completed()
    receipt = json.loads(await fake_redis.get(health.redis_key))
    receipt["body"]["iteration"] += 1
    await fake_redis.set(health.redis_key, health.canonical(receipt), ex=10)
    with pytest.raises(ValueError, match="signature_invalid"):
        await health.check()
