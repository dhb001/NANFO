"""API composition tests with owner/transport doubles; no agent or service I/O."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.telemetry import snmp_composition as composition
from app.modules.telemetry.snmp_config import SNMPError
from tests.unit import test_measured_snmp as protocol_fixtures
from tests.unit.test_measured_snmp import credentials, parsed, protected

binding = protocol_fixtures.binding


@pytest.fixture
def configured(binding, tmp_path):
    binding_path = protected(tmp_path / "binding.json", binding.model_dump(mode="json"))
    credential_path = protected(tmp_path / "credentials.json", credentials())
    return Settings(
        _env_file=None, EXECUTION_MODE="production", TELEMETRY_RUNTIME_ADAPTER_MODE="measured_snmp",
        TELEMETRY_MEASURED_SNMP_BINDING_PATH=binding_path,
        TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH=credential_path,
    )


@pytest.fixture
def owners(monkeypatch):
    authorize = AsyncMock()
    monkeypatch.setattr(composition.SNMPOwnerBoundary, "authorize", authorize)
    monkeypatch.setattr(composition.NetSNMPTransport, "check_available", lambda _: None)
    return authorize


async def build(settings, ingestion=None):
    return await composition.build_measured_snmp_poll_action(
        settings=settings, session_factory=MagicMock(), redis=MagicMock(),
        ingestion_service=ingestion or MagicMock(),
    )


def test_default_configuration_preserves_stub_demo_and_measured_defaults():
    settings = Settings(_env_file=None)
    assert settings.TELEMETRY_RUNTIME_ADAPTER_MODE == "stub"
    assert settings.EXECUTION_MODE == "demo"
    assert settings.TELEMETRY_MEASURED_SNMP_BINDING_PATH is None
    assert settings.TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH is None
    assert settings.TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS == 10
    assert settings.TELEMETRY_MEASURED_SNMP_POLL_TIMEOUT_SECONDS == 60


@pytest.mark.parametrize("selector", ["stub", "seeded", "snmp", "grpc", "emulation", "unknown-legacy-fallback"])
def test_legacy_selectors_do_not_require_new_configuration(selector):
    assert Settings(_env_file=None, TELEMETRY_RUNTIME_ADAPTER_MODE=selector).TELEMETRY_RUNTIME_ADAPTER_MODE == selector


@pytest.mark.parametrize("overrides", [
    {"TELEMETRY_MEASURED_SNMP_BINDING_PATH": None},
    {"TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH": None},
    {"EXECUTION_MODE": "demo"},
    {"TELEMETRY_MEASURED_SNMP_BINDING_PATH": "relative.json"},
    {"TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH": "/run/../secret"},
    {"TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH": "/run/secret\n"},
    {"TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS": 0},
    {"TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS": True},
    {"TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS": float("nan")},
    {"TELEMETRY_MEASURED_SNMP_POLL_TIMEOUT_SECONDS": float("inf")},
    {"TELEMETRY_MEASURED_SNMP_POLL_TIMEOUT_SECONDS": 301},
])
def test_measured_settings_reject_invalid_inputs(configured, overrides):
    data = configured.model_dump(exclude_computed_fields=True)
    data.update(overrides)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **data)


def test_measured_settings_require_distinct_paths(configured):
    data = configured.model_dump(exclude_computed_fields=True)
    data["TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH"] = data["TELEMETRY_MEASURED_SNMP_BINDING_PATH"]
    with pytest.raises(ValidationError, match="distinct"):
        Settings(_env_file=None, **data)


def test_environment_settings_parse_paths_and_limits(monkeypatch, configured):
    monkeypatch.setenv("EXECUTION_MODE", "production")
    monkeypatch.setenv("TELEMETRY_RUNTIME_ADAPTER_MODE", " measured_snmp ")
    monkeypatch.setenv("TELEMETRY_MEASURED_SNMP_BINDING_PATH", str(configured.TELEMETRY_MEASURED_SNMP_BINDING_PATH))
    monkeypatch.setenv("TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH", str(configured.TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH))
    monkeypatch.setenv("TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS", "12.5")
    settings = Settings(_env_file=None)
    assert settings.TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS == 12.5
    assert settings.TELEMETRY_MEASURED_SNMP_BINDING_PATH.is_absolute()


async def test_build_preflights_without_transport_and_action_rechecks(configured, binding, owners, monkeypatch):
    get = AsyncMock(return_value=parsed(binding))
    monkeypatch.setattr(composition.NetSNMPTransport, "get", get)
    ingestion = MagicMock(ingest=AsyncMock())
    action = await build(configured, ingestion)
    owners.assert_awaited_once_with(binding, True)
    get.assert_not_awaited()
    ingestion.ingest.assert_not_awaited()
    assert await action() is None
    assert ingestion.ingest.await_count == 3
    assert [call.args[1] for call in owners.await_args_list] == [True, True, False, False, False, True, True, True]


async def test_build_preserves_supplied_dependency_lifetimes(configured, owners, monkeypatch):
    factory, redis, ingestion = MagicMock(), MagicMock(), MagicMock()
    original = composition.SNMPOwnerBoundary
    boundary = MagicMock(side_effect=original)
    monkeypatch.setattr(composition, "SNMPOwnerBoundary", boundary)
    await composition.build_measured_snmp_poll_action(
        settings=configured, session_factory=factory, redis=redis, ingestion_service=ingestion,
    )
    assert boundary.call_args.kwargs["session_factory"] is factory
    assert boundary.call_args.kwargs["redis"] is redis
    redis.aclose.assert_not_called()
    factory.assert_not_called()  # owner method is doubled, no eager global session


async def test_preflight_revocation_fails_without_device_request(configured, owners, monkeypatch):
    get = AsyncMock()
    monkeypatch.setattr(composition.NetSNMPTransport, "get", get)
    owners.side_effect = SNMPError("collector_permission_denied")
    with pytest.raises(SNMPError, match="permission_denied"):
        await build(configured)
    get.assert_not_awaited()


async def test_wrong_selector_is_not_silently_wired():
    with pytest.raises(SNMPError, match="selector_required"):
        await build(Settings(_env_file=None))


async def test_mode_mismatch_fails_before_authority(configured, owners):
    configured.EXECUTION_MODE = "emulation"
    with pytest.raises(SNMPError, match="execution_mode_mismatch"):
        await build(configured)
    owners.assert_not_awaited()


@pytest.mark.parametrize("change,reason", [
    ({"max_pending_seconds": 2.0}, "pending_ttl"),
    ({"max_interval_seconds": 12.0}, "rate_window"),
])
async def test_incoherent_binding_timing_rejected(configured, binding, owners, change, reason):
    data = binding.model_dump(mode="json")
    data.update(change)
    protected(configured.TELEMETRY_MEASURED_SNMP_BINDING_PATH, data)
    with pytest.raises(SNMPError, match=reason):
        await build(configured)
    owners.assert_not_awaited()


async def test_insufficient_outer_timeout_rejected(configured, owners):
    configured.TELEMETRY_MEASURED_SNMP_POLL_TIMEOUT_SECONDS = 2
    with pytest.raises(SNMPError, match="transport_budget"):
        await build(configured)
    owners.assert_not_awaited()


async def test_insecure_credentials_rejected_at_build(configured, owners):
    configured.TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH.chmod(0o644)
    with pytest.raises(SNMPError, match="protected_config"):
        await build(configured)
    owners.assert_not_awaited()


async def test_unavailable_client_rejected_at_build(configured, owners, monkeypatch):
    monkeypatch.setattr(composition.NetSNMPTransport, "check_available", MagicMock(side_effect=SNMPError("unavailable")))
    with pytest.raises(SNMPError, match="unavailable"):
        await build(configured)
    owners.assert_not_awaited()


async def test_action_redacts_failure_and_retains_stable_pending_batch(configured, binding, owners, monkeypatch):
    get = AsyncMock(return_value=parsed(binding))
    monkeypatch.setattr(composition.NetSNMPTransport, "get", get)
    ingestion = MagicMock(ingest=AsyncMock(side_effect=["ok", RuntimeError("secret redis URL")]))
    action = await build(configured, ingestion)
    with pytest.raises(SNMPError, match="measured_snmp_poll_failed") as caught:
        await action()
    assert "secret" not in str(caught.value) and caught.value.__suppress_context__
    event_id = ingestion.ingest.await_args_list[0].kwargs["event_id"]
    ingestion.ingest.side_effect = None
    await action()
    assert ingestion.ingest.await_args_list[2].kwargs["event_id"] == event_id
    assert get.await_count == 1


async def test_poll_rechecks_authority_after_build(configured, owners, monkeypatch):
    get = AsyncMock()
    monkeypatch.setattr(composition.NetSNMPTransport, "get", get)
    action = await build(configured)
    owners.side_effect = SNMPError("collector_permission_denied")
    with pytest.raises(SNMPError, match="permission_denied"):
        await action()
    get.assert_not_awaited()


@pytest.mark.parametrize("stage", ["build", "poll"])
async def test_outer_deadline_and_cancellation(configured, owners, monkeypatch, stage):
    timeout = asyncio.timeout
    monkeypatch.setattr(composition.asyncio, "timeout", lambda _: timeout(0.02))
    finalized = []

    async def blocked(*args):
        try:
            await asyncio.sleep(10)
        finally:
            finalized.append(True)

    if stage == "build":
        owners.side_effect = blocked
        with pytest.raises(SNMPError, match="preflight_timeout"):
            await build(configured)
    else:
        action = await build(configured)
        owners.side_effect = blocked
        with pytest.raises(SNMPError, match="poll_timeout"):
            await action()
    assert finalized == [True]
